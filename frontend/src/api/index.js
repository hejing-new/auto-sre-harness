const BASE = ""

export async function fetchHistoryList(limit = 50, offset = 0) {
  const res = await fetch(`${BASE}/api/history?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function fetchHistoryDetail(taskId) {
  const res = await fetch(`${BASE}/api/history/${taskId}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function streamDiagnose(alert, container = "auto-sre-sandbox", maxIterations = 10) {
  const params = new URLSearchParams({ alert, container, max_iterations: maxIterations })
  const url = `${BASE}/api/stream-diagnose?${params.toString()}`
  return new EventSource(url)
}
