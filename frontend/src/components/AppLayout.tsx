import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Library,
  ListTodo,
  Settings2,
  LogOut,
  Menu,
  ArrowUpRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import ThemeToggle from "./ThemeToggle";
import ApiConnectionSettings from "./ApiConnectionSettings";
import { cn } from "@/lib/utils";
const nav = [
  { to: "/", label: "总览", icon: LayoutDashboard },
  { to: "/galleries", label: "下载任务", icon: ListTodo },
  { to: "/settings", label: "设置", icon: Settings2 },
];
function Navigation() {
  return (
    <nav className="space-y-1">
      {nav.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors",
              isActive
                ? "bg-accent font-medium text-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )
          }
        >
          <Icon className="size-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
export default function AppLayout({
  authEnabled,
  onLogout,
}: {
  authEnabled: boolean;
  onLogout: () => void;
}) {
  const path = useLocation().pathname;
  return (
    <div className="min-h-svh">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-56 flex-col border-r bg-card px-4 py-6 md:flex">
        <a href="/" className="mb-10 flex items-center gap-3 px-2">
          <div className="rounded-lg bg-primary p-2 text-primary-foreground">
            <Library className="size-5" />
          </div>
          <div>
            <div className="font-semibold tracking-wider">EFDRR</div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              收藏与下载管理
            </div>
          </div>
        </a>
        <Navigation />
        <div className="mt-auto space-y-5 px-2">
          <a
            className="flex items-center justify-between text-xs text-muted-foreground hover:text-foreground"
            href="https://e-hentai.org/favorites.php"
            target="_blank"
            rel="noreferrer"
          >
            打开收藏夹
            <ArrowUpRight className="size-3.5" />
          </a>
          <div className="flex items-center justify-between border-t pt-4 text-xs text-muted-foreground">
            <span>EFDRR</span>
            <span className="font-mono">v{__APP_VERSION__}</span>
          </div>
        </div>
      </aside>
      <div className="md:pl-56">
        <header className="sticky top-0 z-10 flex h-16 items-center gap-3 border-b bg-background/95 px-5 backdrop-blur md:px-8">
          <Sheet>
            <SheetTrigger asChild>
              <Button
                className="md:hidden"
                variant="ghost"
                size="icon"
                aria-label="打开导航"
              >
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 p-6">
              <SheetTitle>EFDRR</SheetTitle>
              <SheetDescription>收藏与下载管理</SheetDescription>
              <Navigation />
            </SheetContent>
          </Sheet>
          <span className="text-sm text-muted-foreground">
            工作空间 <span className="mx-2 opacity-40">/</span>{" "}
            <span className="text-foreground">
              {nav.find((item) => item.to === path)?.label || "总览"}
            </span>
          </span>
          <div className="ml-auto flex items-center gap-2">
            <ApiConnectionSettings />
            <ThemeToggle />
            {authEnabled && (
              <Button
                variant="ghost"
                size="icon"
                aria-label="退出登录"
                onClick={onLogout}
              >
                <LogOut />
              </Button>
            )}
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] p-5 md:p-8 lg:p-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
