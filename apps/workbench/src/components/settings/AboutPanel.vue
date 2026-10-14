<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const VERSION = '0.1.0'
</script>

<template>
  <div class="panel">
    <h3>{{ t('common.about') }}</h3>
    <div class="about-body">
      <div class="about-logo">◆</div>
      <h4>TopoCode</h4>
      <p class="muted">{{ t('home.sub') }}</p>
      <p>{{ t('common.version') }} v{{ VERSION }}</p>
      <p class="muted">
        {{ t('settings.about.modules') }}
      </p>
    </div>
  </div>
</template>
