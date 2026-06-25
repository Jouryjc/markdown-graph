import { NavLink } from "react-router-dom";
import { Search, Share2, Boxes, BarChart3, Upload, Settings } from "lucide-react";

const links = [
  { to: "/", label: "Search", icon: Search, end: true },
  { to: "/graph", label: "Graph", icon: Share2, end: false },
  { to: "/sag", label: "SAG", icon: Boxes, end: false },
  { to: "/stats", label: "Stats", icon: BarChart3, end: false },
  { to: "/upload", label: "上传", icon: Upload, end: false },
  { to: "/settings", label: "设置", icon: Settings, end: false },
];

export default function NavBar() {
  return (
    <nav className="flex items-center gap-1 border-b border-gray-200 bg-white px-4 py-2">
      <span className="mr-4 font-semibold tracking-tight">mdgraph</span>
      {links.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            [
              "flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium",
              isActive
                ? "bg-blue-50 text-blue-700"
                : "text-gray-600 hover:bg-gray-100",
            ].join(" ")
          }
        >
          <Icon size={16} />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
