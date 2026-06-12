import { NavLink } from "react-router-dom";

interface ShellNavGroup {
  label: string;
  links: ShellNavLink[];
}

interface ShellNavLink {
  label: string;
  to: string;
}

interface ShellNavProps {
  groups: ShellNavGroup[];
}

export function ShellNav({ groups }: ShellNavProps) {
  return (
    <nav className="nav-list" aria-label="主导航">
      {groups.map((group) => (
        <div className="nav-section" key={group.label}>
          <span className="nav-section-title">{group.label}</span>
          {group.links.map(({ to, label }) => (
            <NavLink key={to} to={to} end={to === "/console" || to === "/portal"} data-nav-path={to}>
              <span>{label}</span>
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

export type { ShellNavGroup, ShellNavLink };
