<script setup lang="ts">
// A reset under way, or just finished: its steps, the driver's log, and which
// members have the packets that carry it. Polls while there's anything left
// to happen.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiError, gameResetApi, type ResetDetail } from '@/services/api'

const props = defineProps<{ leagueId: number; resetId: number }>()
const emit = defineEmits<{ finished: [reset: ResetDetail] }>()

const reset = ref<ResetDetail | null>(null)
const error = ref('')
const showLog = ref(false)
let timer: number | undefined

const STEPS = [
  { stage: 'queued', label: 'Started' },
  { stage: 'lock', label: 'Processing paused for the reset' },
  { stage: 'backup', label: 'Game backed up' },
  { stage: 'editor', label: "Settings typed into the game's reset editor" },
  { stage: 'saved', label: 'Both pages read back and saved, league-wide' },
  { stage: 'processing', label: 'PLANETARY run' },
  { stage: 'sent', label: 'Game Start on its way to members' }
]
const ENDINGS: Record<string, string> = {
  restored: 'Something was wrong: the game was put back as it was',
  failed: 'Stopped before the game was touched',
  interrupted: 'The hub restarted during the reset'
}

const reached = computed(() => new Map((reset.value?.progress ?? []).map((p) => [p.stage, p.at])))
const ending = computed(() =>
  (reset.value?.progress ?? []).map((p) => p.stage).find((s) => s in ENDINGS)
)
const running = computed(() => reset.value?.status === 'applying')

function state(stage: string): 'done' | 'active' | 'waiting' | 'skipped' {
  if (reached.value.has(stage)) {
    // The stage being worked on is the last one reached, until the next lands.
    const last = reset.value!.progress[reset.value!.progress.length - 1].stage
    return running.value && last === stage && stage !== 'queued' ? 'active' : 'done'
  }
  return running.value ? 'waiting' : 'skipped'
}

const downloaded = computed(() => reset.value?.members.filter((m) => m.downloaded_at).length ?? 0)
const allDownloaded = computed(
  () => !!reset.value?.members.length && downloaded.value === reset.value.members.length
)

function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString()
}

async function poll() {
  try {
    const { data } = await gameResetApi.reset(props.leagueId, props.resetId)
    const was = reset.value?.status
    reset.value = data
    error.value = ''
    if (was === 'applying' && data.status !== 'applying') emit('finished', data)
  } catch (e) {
    error.value = apiError(e, 'Could not read the reset')
  }
  // Fast while the hub works; slowly while members are still downloading.
  const next = running.value ? 2000 : reset.value?.status === 'applied' && !allDownloaded.value ? 30000 : 0
  if (next) timer = window.setTimeout(poll, next)
}

watch(() => props.resetId, () => {
  window.clearTimeout(timer)
  reset.value = null
  poll()
})
onMounted(poll)
onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
  <section class="card mb-4 progress-card" :class="reset?.status">
    <div class="card-header">
      <h3>
        <template v-if="!reset || running">Reset under way</template>
        <template v-else-if="reset.status === 'applied'">Reset performed</template>
        <template v-else>Reset failed</template>
      </h3>
      <span v-if="reset?.applied_by" class="text-muted small">
        by {{ reset.applied_by }}
      </span>
    </div>
    <div class="card-body">
      <div v-if="error" class="alert alert-error mb-2">{{ error }}</div>
      <template v-if="reset">
        <ol class="steps">
          <li v-for="s in STEPS" :key="s.stage" :class="state(s.stage)">
            <span class="mark" aria-hidden="true"></span>
            <span>{{ s.label }}</span>
            <span v-if="reached.get(s.stage)" class="text-muted small">
              {{ formatTime(reached.get(s.stage)) }}
            </span>
          </li>
          <li v-if="ending" class="ended">
            <span class="mark" aria-hidden="true"></span>
            <span>{{ ENDINGS[ending] }}</span>
            <span class="text-muted small">{{ formatTime(reached.get(ending)) }}</span>
          </li>
        </ol>

        <div v-if="reset.error" class="alert mt-2" :class="reset.status === 'failed' ? 'alert-error' : 'alert-warning'">
          {{ reset.error }}
        </div>

        <p v-if="reset.game_start" class="mt-2">
          New game started {{ reset.game_start.replace('T', ' ') }}.
          <span v-if="reset.confirmed === true" class="badge badge-success">Confirmed by the Game Start</span>
          <span v-else-if="reset.confirmed === false" class="badge badge-danger">
            The Game Start disagrees: {{ reset.mismatches.join(', ') }}
          </span>
        </p>

        <template v-if="reset.members.length">
          <h4>Members: {{ downloaded }} of {{ reset.members.length }} have it</h4>
          <p class="text-muted small">
            Each member's game resets on its first run after it downloads its packet.
          </p>
          <table class="table members">
            <thead>
              <tr><th>BBS</th><th>Packet</th><th>Downloaded</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in reset.members" :key="m.filename">
                <td>{{ m.bbs_name ?? `BBS ${m.bbs_index}` }}</td>
                <td><code>{{ m.filename }}</code></td>
                <td>
                  <span v-if="m.downloaded_at">{{ formatTime(m.downloaded_at) }}</span>
                  <span v-else class="text-muted">waiting</span>
                </td>
              </tr>
            </tbody>
          </table>
        </template>

        <button v-if="reset.transcript" class="btn btn-secondary btn-sm mt-2" @click="showLog = !showLog">
          {{ showLog ? 'Hide' : 'Show' }} the editor log
        </button>
        <pre v-if="showLog" class="log">{{ reset.transcript }}</pre>
        <p v-if="reset.backup_path && showLog" class="text-muted small">
          Backup: <code>{{ reset.backup_path }}</code>
        </p>
      </template>
      <div v-else class="spinner"></div>
    </div>
  </section>
</template>

<style scoped>
.progress-card.applying {
  border-left: 4px solid var(--color-primary);
}

.progress-card.applied {
  border-left: 4px solid var(--color-success);
}

.progress-card.failed {
  border-left: 4px solid var(--color-danger);
}

.card-header {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
}

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
}

.steps li {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  padding: 0.25rem 0;
}

.mark {
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 50%;
  border: 2px solid var(--color-border);
  flex: none;
}

.done .mark {
  background: var(--color-success);
  border-color: var(--color-success);
}

.active .mark {
  border-color: var(--color-primary);
  border-top-color: transparent;
  animation: spin 0.9s linear infinite;
}

.waiting,
.skipped {
  color: var(--color-text-muted);
}

.skipped span:not(.mark) {
  text-decoration: line-through;
}

.ended .mark {
  background: var(--color-danger);
  border-color: var(--color-danger);
}

h4 {
  margin: 1rem 0 0.25rem;
  font-size: 0.95rem;
}

.small {
  font-size: 0.85rem;
}

.members td {
  font-size: 0.85rem;
}

.log {
  margin-top: 0.5rem;
  padding: 0.75rem;
  max-height: 20rem;
  overflow: auto;
  font-size: 0.8rem;
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
