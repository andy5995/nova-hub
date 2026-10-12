<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { applicationsApi, type Application, type ApplicationReview } from '@/services/api'
import { useCopy } from '@/clipboard'

// The join queue. Admin only. Approving a join creates the BBS, its owner,
// addresses and memberships in one go, and hands back a claim link bound to
// the applicant; a league request adds memberships to a BBS already here.

interface GrantRow {
  league_id: number
  full_id: string
  name: string
  hub_address: string | null
  include: boolean
  bbs_index: string
  ftn_address: string
  taken: ApplicationReview['leagues'][number]['taken']
}

const route = useRoute()
const { copy, label: copyLabel } = useCopy()

const status = ref<'pending' | 'all'>('pending')
const rows = ref<Application[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const review = ref<ApplicationReview | null>(null)
const grants = ref<GrantRow[]>([])
const clientId = ref('')
const bbsName = ref('')
const note = ref('')
const deciding = ref(false)
const dialogError = ref<string | null>(null)
const rejecting = ref(false)
const result = ref<{
  bbs_name: string
  client_id: number
  claim_url: string | null
  claim_expires_at: string | null
  nodelist_problems: string[]
} | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    rows.value = (await applicationsApi.list(status.value)).data
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Could not load applications.'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  const id = Number(route.query.id)
  if (id) open(id)
})

async function open(id: number) {
  dialogError.value = null
  rejecting.value = false
  note.value = ''
  try {
    const r = (await applicationsApi.review(id)).data
    review.value = r
    clientId.value = r.client_id_suggestion ?? ''
    bbsName.value = r.application.bbs_name
    grants.value = r.leagues.map((l) => ({
      league_id: l.league_id,
      full_id: l.full_id,
      name: l.name,
      hub_address: l.hub_address,
      include: true,
      bbs_index: String(l.bbs_index),
      ftn_address: l.ftn_address ?? '',
      taken: l.taken,
    }))
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Could not open that application.'
  }
}

function close() {
  review.value = null
  result.value = null
}

const isJoin = computed(() => review.value?.application.kind === 'join')
const isPending = computed(() => review.value?.application.status === 'pending')

// Keep one index and address across leagues unless the admin says otherwise.
function copyFirstToRest() {
  const [first, ...rest] = grants.value.filter((g) => g.include)
  if (!first) return
  for (const g of rest) {
    g.bbs_index = first.bbs_index
    g.ftn_address = first.ftn_address
  }
}

function clash(g: GrantRow): string | null {
  const holder = g.taken.find((t) => t.bbs_index === Number(g.bbs_index))
  return holder ? `#${holder.bbs_index} is ${holder.bbs_name}` : null
}

async function approve() {
  if (!review.value || deciding.value) return
  dialogError.value = null
  const chosen = grants.value.filter((g) => g.include)
  if (!chosen.length) {
    dialogError.value = 'Grant at least one league.'
    return
  }
  deciding.value = true
  try {
    const response = (
      await applicationsApi.approve(review.value.application.id, {
        grants: chosen.map((g) => ({
          league_id: g.league_id,
          bbs_index: Number(g.bbs_index),
          ftn_address: g.ftn_address.trim(),
        })),
        client_id: isJoin.value ? clientId.value.trim() : undefined,
        bbs_name: isJoin.value ? bbsName.value.trim() : undefined,
        note: note.value.trim() || undefined,
      })
    ).data
    result.value = { bbs_name: response.application.bbs_name, ...response }
    review.value = null
    await load()
  } catch (e: any) {
    dialogError.value = e.response?.data?.detail || 'Could not approve it.'
  } finally {
    deciding.value = false
  }
}

async function reject() {
  if (!review.value || deciding.value) return
  deciding.value = true
  dialogError.value = null
  try {
    await applicationsApi.reject(review.value.application.id, note.value.trim())
    review.value = null
    await load()
  } catch (e: any) {
    dialogError.value = e.response?.data?.detail || 'Could not reject it.'
  } finally {
    deciding.value = false
  }
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : ''
}

function location(a: Application): string {
  return [a.city, a.state, a.country].filter(Boolean).join(', ') || '-'
}
</script>

<template>
  <AppLayout>
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Applications</h1>
          <p class="text-muted">BBSes asking to join, and BBSes asking for more leagues</p>
        </div>
        <select v-model="status" @change="load()">
          <option value="pending">Waiting</option>
          <option value="all">All</option>
        </select>
      </header>

      <div v-if="error" class="alert alert-error">{{ error }}</div>

      <div class="card">
        <div class="card-body" style="padding: 0;">
          <table class="table">
            <thead>
              <tr>
                <th>Sent</th>
                <th>BBS</th>
                <th>Asking for</th>
                <th>From</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!loading && rows.length === 0">
                <td colspan="6" class="text-center text-muted" style="padding: 2rem;">
                  {{ status === 'pending' ? 'Nothing waiting' : 'No applications yet' }}
                </td>
              </tr>
              <tr v-for="a in rows" :key="a.id">
                <td class="nowrap text-muted">{{ when(a.created_at) }}</td>
                <td>
                  <router-link v-if="a.client_id" :to="`/clients/${a.client_id}`">{{ a.bbs_name }}</router-link>
                  <span v-else>{{ a.bbs_name }}</span>
                  <div class="text-muted small">{{ a.kind === 'join' ? 'New BBS' : 'More leagues' }}</div>
                </td>
                <td class="font-mono small">{{ a.leagues.map((l) => l.full_id).join(', ') }}</td>
                <td>
                  {{ a.applicant }}
                  <div class="text-muted small">{{ a.email }}</div>
                </td>
                <td><span class="badge" :class="`badge-${a.status}`">{{ a.status }}</span></td>
                <td class="actions">
                  <button class="btn btn-sm" :class="a.status === 'pending' ? 'btn-primary' : 'btn-secondary'"
                          @click="open(a.id)">
                    {{ a.status === 'pending' ? 'Review' : 'View' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Review -->
      <div v-if="review" class="modal-overlay" @click.self="close">
        <div class="modal modal-wide">
          <div class="modal-header">
            <h3>{{ isJoin ? 'Join' : 'More leagues' }}: {{ review.application.bbs_name }}</h3>
            <button class="modal-close" @click="close">&times;</button>
          </div>
          <div class="modal-body">
            <dl class="details">
              <dt>Applicant</dt>
              <dd>{{ review.application.applicant }} · {{ review.application.email }}</dd>
              <template v-if="isJoin">
                <dt>Sysop</dt>
                <dd>{{ review.application.sysop_name || '-' }}</dd>
                <dt>Location</dt>
                <dd>{{ location(review.application) }}</dd>
                <dt>Software</dt>
                <dd>{{ review.application.software || '-' }}</dd>
                <dt>Address</dt>
                <dd class="font-mono">{{ review.application.address || '-' }}</dd>
                <dt>Runs on</dt>
                <dd>{{ review.application.os === 'windows' ? 'Windows' : review.application.os === 'linux' ? 'Linux' : '-' }}</dd>
              </template>
              <template v-else>
                <dt>BBS</dt>
                <dd>
                  <router-link :to="`/clients/${review.application.client_id}`">{{ review.application.bbs_name }}</router-link>
                  <span v-if="review.client_addresses.length" class="text-muted">
                    · holds {{ review.client_addresses.join(', ') }}
                  </span>
                </dd>
              </template>
              <dt>Sent</dt>
              <dd>{{ when(review.application.created_at) }}</dd>
            </dl>
            <p v-if="review.application.note" class="applicant-note">{{ review.application.note }}</p>

            <template v-if="isPending">
              <template v-if="isJoin">
                <div class="form-row">
                  <label>BBS name <input v-model="bbsName" maxlength="100" /></label>
                  <label>Client ID <input v-model="clientId" maxlength="64" class="font-mono" /></label>
                </div>
              </template>

              <h4>Leagues</h4>
              <table class="table grants">
                <thead>
                  <tr>
                    <th>Grant</th>
                    <th>League</th>
                    <th>BBS #</th>
                    <th>FTN address</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="g in grants" :key="g.league_id">
                    <td><input v-model="g.include" type="checkbox" /></td>
                    <td>
                      <span class="font-mono">{{ g.full_id }}</span> {{ g.name }}
                      <div class="text-muted small">
                        Hub {{ g.hub_address || 'address not set: no nodelist until it is' }}
                      </div>
                    </td>
                    <td>
                      <input v-model="g.bbs_index" type="number" min="1" max="255" class="index" :disabled="!g.include" />
                      <div v-if="g.include && clash(g)" class="small text-danger">{{ clash(g) }}</div>
                    </td>
                    <td>
                      <input v-model="g.ftn_address" placeholder="zone:net/node" class="font-mono" :disabled="!g.include" />
                    </td>
                  </tr>
                </tbody>
              </table>
              <p class="small text-muted">
                A BBS keeps one index across leagues where it can.
                <button v-if="grants.length > 1" type="button" class="link-button" @click="copyFirstToRest">
                  Use the first row's for all
                </button>
              </p>
              <details class="taken">
                <summary class="small">Who holds what in these leagues</summary>
                <div v-for="g in grants" :key="g.league_id" class="small">
                  <strong class="font-mono">{{ g.full_id }}</strong>:
                  <span v-if="!g.taken.length" class="text-muted">no members yet</span>
                  {{ g.taken.map((t) => `#${t.bbs_index} ${t.bbs_name}${t.ftn_address ? ` (${t.ftn_address})` : ''}`).join(', ') }}
                </div>
              </details>

              <label class="note">
                {{ rejecting ? 'Why not (the sysop sees this)' : 'Note to the sysop (optional)' }}
                <textarea v-model="note" rows="2" maxlength="2000"></textarea>
              </label>
              <div v-if="dialogError" class="alert alert-danger mt-2">{{ dialogError }}</div>
            </template>

            <template v-else>
              <p>
                <span class="badge" :class="`badge-${review.application.status}`">{{ review.application.status }}</span>
                <template v-if="review.application.reviewed_by">
                  by {{ review.application.reviewed_by }}, {{ when(review.application.reviewed_at) }}
                </template>
              </p>
              <p v-if="review.application.granted.length" class="small">
                Granted: {{ review.application.granted.map((g) => `${g.league} as #${g.bbs_index} (${g.ftn_address})`).join(', ') }}
              </p>
              <p v-if="review.application.decision_note" class="applicant-note">{{ review.application.decision_note }}</p>
            </template>
          </div>
          <div class="modal-footer">
            <template v-if="isPending && !rejecting">
              <button class="btn btn-secondary" :disabled="deciding" @click="rejecting = true">Reject...</button>
              <button class="btn btn-primary" :disabled="deciding" @click="approve">
                {{ deciding ? 'Approving...' : 'Approve' }}
              </button>
            </template>
            <template v-else-if="isPending">
              <button class="btn btn-secondary" :disabled="deciding" @click="rejecting = false">Back</button>
              <button class="btn btn-danger" :disabled="deciding" @click="reject">Reject</button>
            </template>
            <button v-else class="btn btn-primary" @click="close">Close</button>
          </div>
        </div>
      </div>

      <!-- Approved -->
      <div v-if="result" class="modal-overlay">
        <div class="modal">
          <div class="modal-header">
            <h3>Approved: {{ result.bbs_name }}</h3>
          </div>
          <div class="modal-body">
            <template v-if="result.claim_url">
              <p class="mb-4">
                The credentials are waiting for the applicant in the console the next time they sign in.
                You can also send them this link; it only works for them, signed in, and expires
                {{ when(result.claim_expires_at) }}.
              </p>
              <div class="secret-display">
                <input type="text" :value="result.claim_url" readonly class="font-mono" />
                <button type="button" class="btn btn-secondary" @click="copy('link', result.claim_url!, $event)">
                  {{ copyLabel('link') }}
                </button>
              </div>
            </template>
            <p v-else>The leagues are added. The BBS's credentials don't change.</p>
            <div v-if="result.nodelist_problems.length" class="alert alert-warning mt-4">
              <div v-for="p in result.nodelist_problems" :key="p">{{ p }}</div>
            </div>
          </div>
          <div class="modal-footer">
            <router-link :to="`/clients/${result.client_id}`" class="btn btn-secondary">Open the BBS</router-link>
            <button type="button" class="btn btn-primary" @click="result = null">Done</button>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
.page {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin-bottom: 0.25rem;
}

.nowrap {
  white-space: nowrap;
}

.small {
  font-size: 0.8125rem;
}

.text-danger {
  color: #dc2626;
}

.badge-pending {
  background: #fef3c7;
  color: #92400e;
}

.badge-approved {
  background: #dcfce7;
  color: #166534;
}

.badge-rejected {
  background: #fee2e2;
  color: #991b1b;
}

.badge-withdrawn {
  background: #e2e8f0;
  color: #475569;
}

.details {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.25rem 1rem;
  margin-bottom: 1rem;
}

.details dt {
  font-weight: 600;
}

.details dd {
  margin: 0;
}

.applicant-note {
  white-space: pre-wrap;
  padding: 0.5rem 0.75rem;
  background: var(--color-background, #f1f5f9);
  border-radius: var(--radius-md, 6px);
  margin-bottom: 1rem;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.form-row label,
.note {
  display: block;
  font-weight: 500;
}

.form-row input,
.note textarea {
  display: block;
  width: 100%;
  margin-top: 0.25rem;
}

h4 {
  margin: 0.5rem 0;
}

.grants input.index {
  width: 5rem;
}

.grants td {
  vertical-align: top;
}

.link-button {
  background: none;
  border: none;
  padding: 0;
  color: var(--color-primary);
  cursor: pointer;
  text-decoration: underline;
  font-size: inherit;
}

.taken {
  margin-bottom: 1rem;
}

.taken summary {
  cursor: pointer;
  margin-bottom: 0.25rem;
}

.secret-display {
  display: flex;
  gap: 0.5rem;
}

.secret-display input {
  flex: 1;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  width: 100%;
  max-width: 520px;
  max-height: calc(100vh - 2rem);
  display: flex;
  flex-direction: column;
}

.modal-wide {
  max-width: 760px;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--color-border);
}

.modal-header h3 {
  margin: 0;
}

.modal-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--color-text-muted);
  line-height: 1;
}

.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--color-border);
}
</style>
