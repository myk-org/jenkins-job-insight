import { Link, useLocation } from 'react-router-dom'
import { BookOpen, Bug, type LucideIcon } from 'lucide-react'
import { UserBadge } from './UserBadge'
import { useAuth } from '@/lib/auth'
import { GITHUB_REPO_URL } from '@/lib/constants'
import { cn } from '@/lib/utils'

interface ExternalNavLink {
  href: string
  label: string
  title: string
  icon: LucideIcon
}

const EXTERNAL_NAV_LINKS: ExternalNavLink[] = [
  { href: 'https://myk-org.github.io/jenkins-job-insight/', label: 'User Guide', title: 'User Guide', icon: BookOpen },
  { href: `${GITHUB_REPO_URL}/issues/new`, label: 'Report Bug', title: 'Report a bug on GitHub', icon: Bug },
]

const BASE_NAV_LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/history', label: 'History' },
]

export function NavBar() {
  const location = useLocation()
  const { isAdmin } = useAuth()

  const navLinks = isAdmin
    ? [...BASE_NAV_LINKS, { to: '/admin/users', label: 'Users' }]
    : BASE_NAV_LINKS

  return (
    <header className="sticky top-0 z-50 border-b border-border-default bg-surface-card/95 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-6">
          <Link
            to="/"
            className="font-display text-lg font-bold tracking-tight text-text-primary"
          >
            JJI
          </Link>
          <nav className="flex items-center gap-1">
            {navLinks.map(({ to, label }) => (
              <Link
                key={to}
                to={to}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150',
                  (location.pathname === to || (to !== '/' && location.pathname.startsWith(to)))
                    ? 'bg-surface-elevated text-text-primary'
                    : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary',
                )}
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          {EXTERNAL_NAV_LINKS.map(({ href, label, title, icon: Icon }) => (
            <a
              key={href}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              title={title}
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-text-tertiary transition-colors duration-150 hover:bg-surface-hover hover:text-text-secondary"
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </a>
          ))}
          <UserBadge />
        </div>
      </div>
    </header>
  )
}
