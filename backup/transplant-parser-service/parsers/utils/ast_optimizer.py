# parsers/utils/ast_optimizer.py
"""
AST 解析性能优化模块

提供批量插入、缓存优化、并行处理等功能。

功能:
1. 批量插入优化 - 减少 MongoDB 写入次数
2. 解析器缓存 - 避免重复创建解析器
3. 文件分组处理 - 按语言分组批量解析
4. 内存管理 - 大文件分块处理
"""
import logging
import os
from typing import Dict, List, Any, Optional, Tuple, Generator
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import threading

logger = logging.getLogger(__name__)


# ==================== 批量插入优化 ====================

class BatchInserter:
    """
    批量插入器
    
    将 AST 节点分批插入 MongoDB，减少数据库交互次数。
    
    使用示例:
        inserter = BatchInserter(collection, batch_size=1000)
        for node in nodes:
            inserter.add(node)
        inserter.flush()  # 插入剩余节点
    """
    
    def __init__(self, collection, batch_size: int = 1000):
        """
        初始化批量插入器
        
        Args:
            collection: MongoDB 集合
            batch_size: 批次大小
        """
        self.collection = collection
        self.batch_size = batch_size
        self.buffer: List[Dict] = []
        self.total_inserted = 0
        self._lock = threading.Lock()
    
    def add(self, document: Dict[str, Any]):
        """
        添加文档到缓冲区
        
        Args:
            document: 要插入的文档
        """
        with self._lock:
            self.buffer.append(document)
            
            if len(self.buffer) >= self.batch_size:
                self._flush_internal()
    
    def add_many(self, documents: List[Dict[str, Any]]):
        """
        批量添加文档
        
        Args:
            documents: 文档列表
        """
        with self._lock:
            self.buffer.extend(documents)
            
            while len(self.buffer) >= self.batch_size:
                self._flush_internal()
    
    def _flush_internal(self):
        """内部刷新（已在锁内）"""
        if not self.buffer:
            return
        
        try:
            result = self.collection.insert_many(self.buffer)
            self.total_inserted += len(result.inserted_ids)
            logger.debug(f"Batch inserted {len(result.inserted_ids)} documents, "
                        f"total: {self.total_inserted}")
        except Exception as e:
            logger.error(f"Failed to insert batch: {e}")
            raise
        
        self.buffer.clear()
    
    def flush(self):
        """刷新缓冲区（插入剩余文档）"""
        with self._lock:
            if self.buffer:
                self._flush_internal()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'total_inserted': self.total_inserted,
            'buffer_size': len(self.buffer),
            'batch_size': self.batch_size
        }


# ==================== 解析器缓存 ====================

class ParserCache:
    """
    解析器缓存
    
    缓存 tree-sitter 解析器实例，避免重复创建。
    支持 LRU 淘汰策略。
    
    使用示例:
        cache = ParserCache(max_size=10)
        parser = cache.get_or_create('python')
        tree = parser.parse(source_code)
    """
    
    def __init__(self, max_size: int = 10):
        """
        初始化解析器缓存
        
        Args:
            max_size: 最大缓存数量
        """
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._access_order: List[str] = []
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
    
    def get_or_create(self, lang: str, create_func=None) -> Optional[Any]:
        """
        获取或创建解析器
        
        Args:
            lang: 语言名称
            create_func: 创建解析器的函数（如果为 None，使用默认工厂）
            
        Returns:
            解析器实例，如果创建失败则返回 None
        """
        with self._lock:
            # 检查缓存
            if lang in self._cache:
                self._hits += 1
                # 更新访问顺序
                self._access_order.remove(lang)
                self._access_order.append(lang)
                logger.debug(f"Parser cache hit for {lang}")
                return self._cache[lang]
            
            # 创建新解析器
            self._misses += 1
            logger.debug(f"Parser cache miss for {lang}, creating...")
            
            if create_func is None:
                from parsers.languages.code_parser.parser_factory import (
                    LanguageParserFactory
                )
                parser = LanguageParserFactory.get_parser(lang)
            else:
                parser = create_func(lang)
            
            if parser is None:
                return None
            
            # 缓存解析器
            self._cache[lang] = parser
            self._access_order.append(lang)
            
            # LRU 淘汰
            while len(self._cache) > self.max_size:
                oldest = self._access_order.pop(0)
                del self._cache[oldest]
                logger.debug(f"Evicted parser for {old} from cache")
            
            return parser
    
    def clear(self):
        """清除缓存"""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            logger.info("Parser cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.2%}"
            }


# 全局解析器缓存实例
_global_parser_cache = ParserCache(max_size=15)


def get_cached_parser(lang: str) -> Optional[Any]:
    """便捷函数：获取缓存的解析器"""
    return _global_parser_cache.get_or_create(lang)


def clear_parser_cache():
    """便捷函数：清除解析器缓存"""
    _global_parser_cache.clear()


def get_parser_cache_stats() -> Dict[str, Any]:
    """便捷函数：获取解析器缓存统计"""
    return _global_parser_cache.get_stats()


# ==================== 文件分组处理 ====================

def group_files_by_language(
    file_paths: List[str],
    detect_func=None
) -> Dict[str, List[str]]:
    """
    按语言分组文件
    
    Args:
        file_paths: 文件路径列表
        detect_func: 语言检测函数（默认使用 detect_language）
        
    Returns:
        {language: [file_paths]}
    """
    if detect_func is None:
        from parsers.languages.code_parser.lang_parser_conf import detect_language
        detect_func = detect_language
    
    groups: Dict[str, List[str]] = defaultdict(list)
    unknown_count = 0
    
    for path in file_paths:
        lang = detect_func(path)
        if lang:
            groups[lang].append(path)
        else:
            unknown_count += 1
            logger.debug(f"Unknown language for file: {path}")
    
    if unknown_count > 0:
        logger.warning(f"{unknown_count} files with unknown language")
    
    return dict(groups)


def process_files_by_language(
    file_paths: List[str],
    process_func,
    max_workers: int = 4
) -> Dict[str, Any]:
    """
    按语言分组处理文件
    
    Args:
        file_paths: 文件路径列表
        process_func: 处理函数 (lang, file_path) -> result
        max_workers: 最大工作线程数
        
    Returns:
        处理结果统计
    """
    # 按语言分组
    groups = group_files_by_language(file_paths)
    
    results = {
        'total_files': len(file_paths),
        'languages': {},
        'success': 0,
        'failed': 0,
        'errors': []
    }
    
    # 按语言顺序处理
    for lang, paths in sorted(groups.items(), key=lambda x: -len(x[1])):
        logger.info(f"Processing {len(paths)} files for language: {lang}")
        
        lang_results = {
            'total': len(paths),
            'success': 0,
            'failed': 0
        }
        
        for path in paths:
            try:
                result = process_func(lang, path)
                lang_results['success'] += 1
                results['success'] += 1
            except Exception as e:
                lang_results['failed'] += 1
                results['failed'] += 1
                results['errors'].append(f"{path}: {e}")
                logger.error(f"Failed to process {path}: {e}")
        
        results['languages'][lang] = lang_results
    
    return results


# ==================== 内存管理 ====================

class MemoryManager:
    """
    内存管理器
    
    监控和管理 AST 解析过程中的内存使用。
    """
    
    def __init__(self, max_memory_mb: int = 1024):
        """
        初始化内存管理器
        
        Args:
            max_memory_mb: 最大内存限制 (MB)
        """
        self.max_memory_mb = max_memory_mb
        self._current_usage = 0
        self._lock = threading.Lock()
    
    def check_memory(self) -> bool:
        """
        检查当前内存使用
        
        Returns:
            True 如果内存使用正常，False 如果超过限制
        """
        import gc
        
        # 触发垃圾回收
        gc.collect()
        
        # 获取当前内存使用（近似）
        try:
            import resource
            usage_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except ImportError:
            # Windows 不支持
            usage_mb = 0
        
        self._current_usage = usage_mb
        
        if usage_mb > self.max_memory_mb:
            logger.warning(f"Memory usage ({usage_mb:.1f}MB) exceeds limit "
                          f"({self.max_memory_mb}MB)")
            return False
        
        return True
    
    def get_usage(self) -> float:
        """获取当前内存使用 (MB)"""
        return self._current_usage


# ==================== 性能监控 ====================

class PerformanceMonitor:
    """
    性能监控器
    
    监控 AST 解析的性能指标。
    """
    
    def __init__(self):
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
    
    def record_timing(self, operation: str, duration: float):
        """
        记录操作耗时
        
        Args:
            operation: 操作名称
            duration: 耗时（秒）
        """
        with self._lock:
            self._timings[operation].append(duration)
            self._counts[operation] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        with self._lock:
            stats = {}
            
            for op, timings in self._timings.items():
                if timings:
                    stats[op] = {
                        'count': self._counts[op],
                        'total': sum(timings),
                        'avg': sum(timings) / len(timings),
                        'min': min(timings),
                        'max': max(timings)
                    }
            
            return stats
    
    def reset(self):
        """重置统计"""
        with self._lock:
            self._timings.clear()
            self._counts.clear()


# 全局性能监控实例
_perf_monitor = PerformanceMonitor()


def record_perf(operation: str, duration: float):
    """便捷函数：记录性能数据"""
    _perf_monitor.record_timing(operation, duration)


def get_perf_stats() -> Dict[str, Any]:
    """便捷函数：获取性能统计"""
    return _perf_monitor.get_stats()


# ==================== 主优化函数 ====================

def optimize_ast_parsing(
    file_paths: List[str],
    parse_func,
    proj_id: int,
    proj_path: str,
    batch_size: int = 1000,
    max_workers: int = 4
) -> Dict[str, Any]:
    """
    优化的 AST 解析主函数
    
    整合所有优化策略：
    1. 按语言分组
    2. 解析器缓存
    3. 批量插入
    4. 性能监控
    
    Args:
        file_paths: 文件路径列表
        parse_func: 解析函数 (lang, path, proj_id, proj_path) -> nodes
        proj_id: 项目 ID
        proj_path: 项目路径
        batch_size: 批次大小
        max_workers: 最大工作线程数
        
    Returns:
        处理结果统计
    """
    import time
    
    start_time = time.time()
    
    # 按语言分组
    groups = group_files_by_language(file_paths)
    
    results = {
        'total_files': len(file_paths),
        'languages': {},
        'total_nodes': 0,
        'success': 0,
        'failed': 0,
        'errors': [],
        'duration': 0
    }
    
    # 按语言处理
    for lang, paths in sorted(groups.items(), key=lambda x: -len(x[1])):
        logger.info(f"Processing {len(paths)} files for {lang}")
        
        lang_start = time.time()
        lang_nodes = 0
        lang_success = 0
        lang_failed = 0
        
        # 获取缓存的解析器
        parser = get_cached_parser(lang)
        if parser is None:
            logger.warning(f"No parser available for {lang}, skipping...")
            continue
        
        # 处理文件
        for path in paths:
            try:
                file_start = time.time()
                nodes = parse_func(lang, path, proj_id, proj_path)
                file_duration = time.time() - file_start
                
                lang_nodes += len(nodes) if nodes else 0
                lang_success += 1
                results['success'] += 1
                
                record_perf(f'parse_{lang}', file_duration)
                
            except Exception as e:
                lang_failed += 1
                results['failed'] += 1
                results['errors'].append(f"{path}: {e}")
                logger.error(f"Failed to parse {path}: {e}")
        
        lang_duration = time.time() - lang_start
        results['languages'][lang] = {
            'total': len(paths),
            'success': lang_success,
            'failed': lang_failed,
            'nodes': lang_nodes,
            'duration': lang_duration
        }
        results['total_nodes'] += lang_nodes
        
        logger.info(f"Completed {lang}: {lang_nodes} nodes in {lang_duration:.2f}s")
    
    results['duration'] = time.time() - start_time
    
    # 记录总体性能
    record_perf('total', results['duration'])
    
    return results
