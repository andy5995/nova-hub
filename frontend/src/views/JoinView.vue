<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { apiError, applicationsApi, authApi, type Application, type JoinableLeague } from '@/services/api'

// A sysop applying to join with a new BBS. Public, but applying needs a
// sign-in, which confirms the email and keeps out drive-by spam. The admin
// approves from the console; the sysop sees the outcome here, and an
// approved BBS in the console with its credentials waiting.

const authStore = useAuthStore()

const loading = ref(true)
const ssoEnabled = ref(false)
const leagues = ref<JoinableLeague[]>([])
const mine = ref<Application[]>([])
const error = ref<string | null>(null)
const submitting = ref(false)

const form = reactive({
  bbs_name: '',
  sysop_name: '',
  city: '',
  state: '',
  country: '',
  address: '',
  os: '' as '' | 'windows' | 'linux',
  league_ids: [] as number[],
  note: '',
})

const joins = computed(() => mine.value.filter((a) => a.kind === 'join'))
const waiting = computed(() => joins.value.find((a) => a.status === 'pending') ?? null)
const signInUrl = computed(() => authApi.ssoStartUrl('/join'))

async function load() {
  loading.value = true
  error.value = null
  try {
    ssoEnabled.value = (await authApi.methods()).data.sso
    if (authStore.isAuthenticated && !authStore.isAdmin) {
      const [l, m] = await Promise.all([applicationsApi.leagues(), applicationsApi.mine()])
      leagues.value = l.data
      mine.value = m.data
    }
  } catch (e: any) {
    error.value = apiError(e, 'The hub could not be reached.')
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function submit() {
  if (submitting.value) return
  error.value = null
  if (!form.league_ids.length) {
    error.value = 'Choose at least one league.'
    return
  }
  submitting.value = true
  try {
    await applicationsApi.apply({
      kind: 'join',
      ...form,
      os: form.os || null,
    })
    mine.value = (await applicationsApi.mine()).data
  } catch (e: any) {
    error.value = apiError(e, 'The application could not be sent.')
  } finally {
    submitting.value = false
  }
}

async function withdraw(application: Application) {
  error.value = null
  try {
    await applicationsApi.withdraw(application.id)
    mine.value = (await applicationsApi.mine()).data
  } catch (e: any) {
    error.value = apiError(e, 'Could not withdraw it.')
  }
}

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : ''
}

const STATUS_TEXT: Record<Application['status'], string> = {
  pending: 'Waiting for the hub admin',
  approved: 'Approved',
  rejected: 'Not approved',
  withdrawn: 'Withdrawn',
}
</script>

<template>
  <div class="public-page">
    <article class="public-card">
      <h1>Nova Hub</h1>
      <h2>Join with your BBS</h2>

      <p v-if="loading" class="text-muted">Loading...</p>

      <!-- Signed out -->
      <template v-else-if="!authStore.isAuthenticated">
        <p>
          Run a BBS and want to join a Barren Realms Elite or Falcon's Eye league? Apply with your
          BBS's details and the leagues you'd like. The hub admin reviews each application; once
          approved, your BBS's credentials wait for you when you sign in.
        </p>
        <p>
          New to Nova Hub? <router-link to="/how-it-works">How it works</router-link> explains what
          you'll run and what replaces your mailer and tosser.
        </p>
        <a v-if="ssoEnabled" class="btn btn-primary" :href="signInUrl">Sign in to apply</a>
        <div v-else class="alert alert-info">
          This hub isn't taking applications online. Ask the hub admin to add your BBS.
        </div>
        <p class="text-muted small mt-2">
          Signing in confirms your email address. The hub sends no email itself.
        </p>
      </template>

      <!-- An admin has nothing to apply for -->
      <template v-else-if="authStore.isAdmin">
        <p>
          You're signed in as an admin. Applications are reviewed in the console:
          <router-link to="/admin/applications">Applications</router-link>.
        </p>
      </template>

      <template v-else>
        <div v-if="error" class="alert alert-danger">{{ error }}</div>

        <section v-if="joins.length" class="history">
          <h3>Your applications</h3>
          <div v-for="a in joins" :key="a.id" class="application">
            <div class="application-head">
              <strong>{{ a.bbs_name }}</strong>
              <span class="badge" :class="`badge-${a.status}`">{{ STATUS_TEXT[a.status] }}</span>
            </div>
            <p class="text-muted small">
              Sent {{ when(a.created_at) }} for {{ a.leagues.map((l) => l.full_id).join(', ') }}
              <template v-if="a.reviewed_at"> · decided {{ when(a.reviewed_at) }}</template>
            </p>
            <p v-if="a.decision_note" class="decision-note">{{ a.decision_note }}</p>
            <p v-if="a.status === 'approved' && a.client_id">
              <router-link :to="`/clients/${a.client_id}`" class="btn btn-primary btn-sm">
                Collect your credentials
              </router-link>
              Granted:
              {{ a.granted.map((g) => `${g.league} as BBS #${g.bbs_index}`).join(', ') }}.
            </p>
            <button v-if="a.status === 'pending'" class="btn btn-secondary btn-sm" @click="withdraw(a)">
              Withdraw
            </button>
          </div>
        </section>

        <p v-if="waiting" class="text-muted">
          The hub admin will look at it soon. Check back here, or in the console, for the outcome.
        </p>

        <form v-else class="join-form" @submit.prevent="submit">
          <h3>{{ joins.length ? 'Apply again' : 'Your BBS' }}</h3>
          <p class="text-muted small">
            Applying as {{ authStore.user?.email || authStore.username }}. If you already run a BBS on
            this hub, ask the hub admin to make you its owner instead of applying.
          </p>

          <label>
            BBS name <span class="required">*</span>
            <input v-model="form.bbs_name" required maxlength="100" />
            <small>As it appears in the games' nodes file and the league nodelist.</small>
          </label>
          <label>
            Your alias (as sysop)
            <input v-model="form.sysop_name" maxlength="100" />
            <small>We don't need your full name.</small>
          </label>
          <div class="row">
            <label>City <input v-model="form.city" maxlength="50" /></label>
            <label>State or region <input v-model="form.state" maxlength="50" /></label>
            <label>Country <input v-model="form.country" maxlength="50" /></label>
          </div>
          <small class="hint">Your location lines in the nodelist other BBSes see.</small>
          <label>
            Telnet or web address
            <input v-model="form.address" maxlength="200" placeholder="telnet://bbs.example.com:23" />
          </label>
          <fieldset>
            <legend>The machine that will run the games</legend>
            <label class="inline"><input v-model="form.os" type="radio" value="windows" /> Windows</label>
            <label class="inline"><input v-model="form.os" type="radio" value="linux" /> Linux (dosemu2)</label>
          </fieldset>
          <fieldset>
            <legend>Leagues <span class="required">*</span></legend>
            <p v-if="!leagues.length" class="text-muted small">No leagues are open to join right now.</p>
            <label v-for="l in leagues" :key="l.id" class="inline league">
              <input v-model="form.league_ids" type="checkbox" :value="l.id" />
              <span class="font-mono">{{ l.full_id }}</span> {{ l.name }}
            </label>
          </fieldset>
          <label>
            Anything else the admin should know
            <textarea v-model="form.note" rows="3" maxlength="2000"></textarea>
          </label>

          <button type="submit" class="btn btn-primary" :disabled="submitting || !leagues.length">
            {{ submitting ? 'Sending...' : 'Send application' }}
          </button>
        </form>

        <p class="mt-4 small">
          <router-link to="/dashboard">Go to the console</router-link> ·
          <router-link to="/how-it-works">How it works</router-link>
        </p>
      </template>
    </article>
  </div>
</template>

<style scoped>
.public-page {
  min-height: 100vh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
  padding: 3rem 1rem;
}

.public-card {
  width: 100%;
  max-width: 680px;
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 2rem;
}

.public-card h1 {
  font-size: 1.25rem;
  color: var(--color-primary);
  margin-bottom: 1rem;
}

.public-card h2 {
  font-size: 1.75rem;
  margin-bottom: 1rem;
}

.public-card h3 {
  margin: 1.5rem 0 0.75rem;
}

.public-card p {
  margin-bottom: 1rem;
}

.small {
  font-size: 0.875rem;
}

.application {
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-md, 6px);
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
}

.application p {
  margin-bottom: 0.5rem;
}

.application-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.25rem;
}

.decision-note {
  white-space: pre-wrap;
  padding: 0.5rem 0.75rem;
  background: var(--color-background, #f1f5f9);
  border-radius: var(--radius-md, 6px);
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

.join-form label {
  display: block;
  margin-bottom: 0.75rem;
  font-weight: 500;
}

.join-form input:not([type='radio']):not([type='checkbox']),
.join-form textarea {
  display: block;
  width: 100%;
  margin-top: 0.25rem;
  font-weight: normal;
}

.join-form small,
.join-form .hint {
  display: block;
  font-weight: normal;
  color: var(--color-text-muted, #64748b);
  font-size: 0.8125rem;
  margin-top: 0.25rem;
}

.join-form .hint {
  margin: -0.5rem 0 0.75rem;
}

.join-form .row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

.join-form fieldset {
  border: none;
  padding: 0;
  margin: 0 0 1rem;
}

.join-form legend {
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.join-form label.inline {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: normal;
  margin-bottom: 0.375rem;
}

.required {
  color: #dc2626;
}

@media (max-width: 600px) {
  .public-card {
    padding: 1.25rem;
  }

  .join-form .row {
    grid-template-columns: 1fr;
  }
}
</style>
