<script setup>
import { ref } from "vue"
import DiagnosePanel from "./components/DiagnosePanel.vue"
import RealtimePanel from "./components/RealtimePanel.vue"
import HistoryPanel from "./components/HistoryPanel.vue"
import { useDiagnose } from "./composables/useDiagnose"
import { useHistory } from "./composables/useHistory"

const activeTab = ref("diagnose")
const tabs = [
  { id: "diagnose", label: "实时诊断" },
  { id: "history", label: "历史审计" }
]

const {
  logs, isRunning, isCompleted, result, error,
  start: startDiagnose
} = useDiagnose()

const { loadList } = useHistory()

function onStartDiagnose({ alert, container, maxIterations }) {
  startDiagnose(alert, container, maxIterations)
}

function switchTab(tabId) {
  activeTab.value = tabId
  if (tabId === "history") {
    loadList()
  }
}

function tabClass(tabId) {
  const isActive = activeTab.value === tabId
  const base = "relative px-6 py-3 text-sm font-medium transition-all border-b-2 -mb-px"
  if (isActive) return base + " text-cyber-primary border-cyber-primary tab-active"
  return base + " text-gray-500 border-transparent hover:text-gray-300 hover:border-gray-600"
}
</script>

<template>
  <div class="scanline min-h-screen flex flex-col">
    <header class="border-b border-cyber-border bg-cyber-darker/80 backdrop-blur-sm sticky top-0 z-40">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded bg-cyber-primary/20 border border-cyber-primary flex items-center justify-center glow-primary">
            <span class="text-cyber-primary text-sm font-bold">S</span>
          </div>
          <div>
            <h1 class="text-cyber-primary font-bold text-lg tracking-wider">AUTO-SRE</h1>
            <p class="text-gray-600 text-xs">AI-Powered Diagnostic Agent</p>
          </div>
        </div>
        <div class="text-xs text-gray-600 font-mono">v1.0.0</div>
      </div>
    </header>

    <nav class="border-b border-cyber-border bg-cyber-darker/40">
      <div class="max-w-7xl mx-auto px-4 flex gap-1">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="switchTab(tab.id)"
          :class="tabClass(tab.id)"
        >
          {{ tab.label }}
          <span
            v-if="isRunning && tab.id === 'diagnose'"
            class="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-cyber-success status-pulse"
          ></span>
        </button>
      </div>
    </nav>

    <main class="flex-1 max-w-7xl mx-auto w-full px-4 py-4">
      <div class="h-[calc(100vh-140px)] bg-cyber-card border border-cyber-border rounded-lg overflow-hidden">
        <DiagnosePanel
          v-if="activeTab === 'diagnose'"
          @start-diagnose="onStartDiagnose"
        >
          <template #log-panel>
            <RealtimePanel
              :logs="logs"
              :is-running="isRunning"
              :is-completed="isCompleted"
              :result="result"
              :error="error"
            />
          </template>
        </DiagnosePanel>

        <HistoryPanel v-if="activeTab === 'history'" />
      </div>
    </main>

    <footer class="border-t border-cyber-border bg-cyber-darker/60 py-2 text-center text-xs text-gray-600">
      Auto-SRE Harness &copy; 2026 | Powered by AI Agent
    </footer>
  </div>
</template>
