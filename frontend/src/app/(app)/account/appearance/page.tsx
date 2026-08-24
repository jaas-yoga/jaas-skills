import { ThemePicker } from "@/components/theme/theme-picker";

export default function AppearanceSettingsPage() {
  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Appearance</h1>
        <p className="text-sm text-muted-foreground">
          Choose how JaaS Skills looks on this browser (ui-design.md §8.5).
        </p>
      </div>
      <ThemePicker />
    </div>
  );
}
