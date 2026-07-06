import { NavLink } from "react-router-dom";

interface ShellNavGroup {
  label: string;
  links: ShellNavLink[];
}

interface ShellNavLink {
  label: string;
  to: string;
  /** 可选的数量角标文本(如待审批数); 为空串时不渲染。 */
  badge?: string;
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
          {group.links.map(({ to, label, badge }) => (
            <NavLink key={to} to={to} end={to === "/console" || to === "/portal"} data-nav-path={to}>
              <span>{label}</span>
              {badge ? (
                <span className="ml-auto inline-flex min-w-[20px] items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-[18px] text-paper">
                  {badge}
                </span>
              ) : null}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

export type { ShellNavGroup, ShellNavLink };
