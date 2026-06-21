<script setup>
import { computed } from "vue"

const props = defineProps({
  logs: { type: Array, required: true },
  isRunning: { type: Boolean, default: false },
  isCompleted: { type: Boolean, default: false },
  result: { type: Object, default: null },
  error: { type: String, default: null }
})

const levelColors = {
  INFO: "text-cyber-primary",
  REASONING: "text-purple-400",
  INTERCEPTING: "text-cyber-warning",
  EXECUTING: "text-cyan-400",
  BLOCKED: "text-cyber-error",
  ERROR: "text-cyber-error",
  SUCCESS: "text-cyber-success",
  DONE: "text-cyber-success"
}

const levelLabels = {
  INFO: "INFO",
  REASONING: "REASONING",
  INTERCEPTING: "INTERCEPT",
  EXECUTING: "EXEC",
  BLOCKED: "BLOCKED",
  ERROR: "ERROR",
  SUCCESS: "SUCCESS",
  DONE: "DONE"
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center gap-3 px-4 py-2 border-b border-cyber-border bg-cyber-darker/50">
      <span v-if="isRunning" class="inline-block w-2 h-2 rounded-full bg-cyber-success status-pulse"></span>
      <span v-else-if="isCompleted" class="inline-block w-2 h-2 rounded-full bg-cyber-primary"></span>
      <span v-else-if="error" class="inline-block w-2 h-2 rounded-full bg-cyber-error"></span>
      <span class="text-sm text-gray-400">
        {{ isRunning ? "诊断中..." : isCompleted ? "诊断完成" : error ? "错误" : "等待开始" }}
      </span>
      <span v-if="isRunning" class="text-xs text-gray-500 ml-auto">{{ logs.length }} logs</span>
    </div>

    <div class="flex-1 overflow-y-auto p-3 space-y-1 font-mono text-sm">
      <div
        v-for="(log, idx) in logs"
        :key="idx"
        class="log-entry flex gap-2 items-start py-1 px-2 rounded hover:bg-white/5 transition-colors"
      >
        <span class="text-gray-600 text-xs whitespace-nowrap">{{ log.timestamp }}</span>
        <span :class="[levelColors[log.level] || 'text-gray-400', 'text-xs font-bold w-20 text-right whitespace-nowrap']">
          {{ levelLabels[log.level] || log.level }}
        </span>
        <span class="text-gray-200 flex-1 break-words">{{ log.message }}</span>
      </div>

      <div v-if="logs.length === 0 && !isRunning" class="flex items-center justify-center h-full text-gray-600">
        <div class="text-center">
          <div class="text-4xl mb-3">🔍</div>
          <p>Input alert to start diagnosis</p>
        </div>
      </div>
    </div>

    <div v-if="isCompleted && result" class="border-t border-cyber-border bg-cyber-success/5 p-3">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-cyber-success font-bold">DONE</span>
        <span v-if="result.total_steps" class="text-xs text-gray-500">
          {{ result.total_steps }} steps | {{ result.commands_executed }} exec | {{ result.commands_blocked }} blocked
        </span>
      </div>
      <p v-if="result.final_analysis" class="text-xs text-gray-400 line-clamp-2">{{ result.final_analysis }}</p>
    </div>

    <div v-if="error" class="border-t border-cyber-border bg-cyber-error/10 p-3 text-cyber-error text-sm">{{ error }}</div>
  </div>
</template>

<style scoped>
.line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
