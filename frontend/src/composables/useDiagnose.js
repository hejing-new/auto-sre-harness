import { ref, readonly } from "vue"
import { streamDiagnose } from "@/api"

export function useDiagnose() {
  const logs = ref([])
  const isRunning = ref(false)
  const isCompleted = ref(false)
  const result = ref(null)
  const error = ref(null)
  let eventSource = null

  function start(alert, container, maxIterations) {
    // Reset state
    logs.value = []
    isRunning.value = true
    isCompleted.value = false
    result.value = null
    error.value = null

    eventSource = streamDiagnose(alert, container, maxIterations)

    eventSource.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data)

        if (entry.type === "done") {
          isCompleted.value = true
          result.value = entry.details || entry
          isRunning.value = false
          eventSource.close()
          return
        }

        if (entry.type === "heartbeat") return

        logs.value.push(entry)
      } catch (e) {
        // ignore malformed data
      }
    }

    eventSource.onerror = (e) => {
      if (isRunning.value) {
        error.value = "连接中断，请重试"
        isRunning.value = false
      }
      if (eventSource) eventSource.close()
    }
  }

  function stop() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    isRunning.value = false
  }

  return {
    logs: readonly(logs),
    isRunning: readonly(isRunning),
    isCompleted: readonly(isCompleted),
    result: readonly(result),
    error: readonly(error),
    start,
    stop
  }
}
