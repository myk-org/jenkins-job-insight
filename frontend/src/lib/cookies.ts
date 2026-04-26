const COOKIE_NAME = 'jji_username'
const GITHUB_TOKEN_KEY = 'jji_github_token'
const JIRA_TOKEN_KEY = 'jji_jira_token'
const JIRA_EMAIL_KEY = 'jji_jira_email'
// Display-only UI hints — NOT an authorization boundary.
// All admin gating is enforced server-side in AuthMiddleware.
const ADMIN_KEY = 'jji_is_admin'
const ROLE_KEY = 'jji_role'

/** Detects values that look like they've been URL-encoded (e.g. %40, %25). */
const ENCODED_PATTERN = /%[0-9A-Fa-f]{2}/

export function looksUrlEncoded(value: string): boolean {
  return ENCODED_PATTERN.test(value)
}

export function getUsername(): string {
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${COOKIE_NAME}=([^;]*)`)
  )
  return match ? match[1] : ''
}

export function setUsername(username: string): void {
  const trimmed = username.trim()
  if (looksUrlEncoded(trimmed)) {
    throw new Error(`Username "${trimmed}" looks URL-encoded. Use the raw value.`)
  }
  document.cookie = `${COOKIE_NAME}=${trimmed}; path=/; max-age=${365 * 24 * 60 * 60}; SameSite=Lax`
}

export function clearUsername(): void {
  document.cookie = `${COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax`
}

export function isLoggedIn(): boolean {
  return getUsername() !== ''
}

function readStoredValue(key: string): string {
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function writeStoredValue(key: string, value: string): void {
  try {
    const trimmed = value.trim()
    if (trimmed) {
      localStorage.setItem(key, trimmed)
    } else {
      localStorage.removeItem(key)
    }
  } catch {
    // Storage unavailable — silently ignore
  }
}

export function getGithubToken(): string {
  return readStoredValue(GITHUB_TOKEN_KEY)
}

export function setGithubToken(token: string): void {
  writeStoredValue(GITHUB_TOKEN_KEY, token)
}

export function getJiraToken(): string {
  return readStoredValue(JIRA_TOKEN_KEY)
}

export function setJiraToken(token: string): void {
  writeStoredValue(JIRA_TOKEN_KEY, token)
}

export function getJiraEmail(): string {
  return readStoredValue(JIRA_EMAIL_KEY)
}

export function setJiraEmail(email: string): void {
  writeStoredValue(JIRA_EMAIL_KEY, email)
}

export function getIsAdmin(): boolean {
  try {
    return localStorage.getItem(ADMIN_KEY) === 'true'
  } catch {
    return false
  }
}

export function setIsAdmin(isAdmin: boolean): void {
  try {
    if (isAdmin) {
      localStorage.setItem(ADMIN_KEY, 'true')
    } else {
      localStorage.removeItem(ADMIN_KEY)
    }
  } catch {
    // ignore
  }
}

export function getRole(): string {
  try {
    return localStorage.getItem(ROLE_KEY) ?? 'user'
  } catch {
    return 'user'
  }
}

export function setRole(role: string): void {
  try {
    if (role && role !== 'user') {
      localStorage.setItem(ROLE_KEY, role)
    } else {
      localStorage.removeItem(ROLE_KEY)
    }
  } catch {
    // ignore
  }
}

export function clearTokens(): void {
  try {
    localStorage.removeItem(GITHUB_TOKEN_KEY)
    localStorage.removeItem(JIRA_TOKEN_KEY)
    localStorage.removeItem(JIRA_EMAIL_KEY)
    localStorage.removeItem(ADMIN_KEY)
    localStorage.removeItem(ROLE_KEY)
  } catch {
    // Storage unavailable — silently ignore
  }
}
