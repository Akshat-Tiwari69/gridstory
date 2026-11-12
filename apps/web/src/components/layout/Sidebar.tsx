import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Activity, MapPin, GitCompareArrows, Clapperboard } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { toQuery, useSessionStore } from '../../stores/sessionStore';
import { IS_DEMO } from '../../services/api';
import './Sidebar.css';

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const NAV_ITEMS: { path: string; Icon: LucideIcon; label: string; end: boolean }[] = [
  { path: '/',          Icon: LayoutDashboard, label: 'Dashboard',  end: true  },
  { path: '/telemetry', Icon: Activity,        label: 'Telemetry',  end: false },
  { path: '/compare',  Icon: GitCompareArrows, label: 'Compare',  end: false },
  { path: '/track',     Icon: MapPin,          label: 'Track Map',  end: false },
];

// The 3D replay is a separate static page (apps/replay3d): published beside the demo, or served by `make replay`.
const REPLAY_URL = IS_DEMO ? `${import.meta.env.BASE_URL}replay/` : 'http://localhost:5180/';

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const search = useSessionStore(toQuery);
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-toggle" onClick={onToggle} title={collapsed ? 'Expand' : 'Collapse'}>
        {collapsed ? '›' : '‹'}
      </div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map(({ path, Icon, label, end }) => (
          <NavLink
            key={path}
            to={{ pathname: path, search }}
            end={end}
            className={({ isActive }) => `sidebar-item${isActive ? ' active' : ''}`}
            title={collapsed ? label : undefined}
          >
            <span className="sidebar-icon">
              <Icon size={16} strokeWidth={1.75} />
            </span>
            {!collapsed && <span className="sidebar-label">{label}</span>}
          </NavLink>
        ))}
        <a href={REPLAY_URL} className="sidebar-item" title={collapsed ? '3D Replay' : undefined}>
          <span className="sidebar-icon">
            <Clapperboard size={16} strokeWidth={1.75} />
          </span>
          {!collapsed && <span className="sidebar-label">3D Replay</span>}
        </a>
      </nav>
    </aside>
  );
}
