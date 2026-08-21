export function delay(ms = 350): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

export async function mockResult<T>(data: T, ms = 350): Promise<T> {
  await delay(ms)
  return data === undefined ? data : (JSON.parse(JSON.stringify(data)) as T)
}
