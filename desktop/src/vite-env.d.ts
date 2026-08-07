/// <reference types="vite/client" />

declare module "lucide-react" {
  import type { ComponentType, SVGProps } from "react";

  export type IconProps = SVGProps<SVGSVGElement> & {
    size?: number | string;
    strokeWidth?: number | string;
    absoluteStrokeWidth?: boolean;
  };

  export const Activity: ComponentType<IconProps>;
  export const AlertCircle: ComponentType<IconProps>;
  export const AlertTriangle: ComponentType<IconProps>;
  export const BadgeCheck: ComponentType<IconProps>;
  export const CheckCircle2: ComponentType<IconProps>;
  export const ChevronRight: ComponentType<IconProps>;
  export const CircleDot: ComponentType<IconProps>;
  export const Clock3: ComponentType<IconProps>;
  export const Cpu: ComponentType<IconProps>;
  export const Download: ComponentType<IconProps>;
  export const Film: ComponentType<IconProps>;
  export const FolderInput: ComponentType<IconProps>;
  export const FolderOpen: ComponentType<IconProps>;
  export const Info: ComponentType<IconProps>;
  export const Image: ComponentType<IconProps>;
  export const KeyRound: ComponentType<IconProps>;
  export const LayoutDashboard: ComponentType<IconProps>;
  export const ListChecks: ComponentType<IconProps>;
  export const ListPlus: ComponentType<IconProps>;
  export const LoaderCircle: ComponentType<IconProps>;
  export const LogOut: ComponentType<IconProps>;
  export const Maximize2: ComponentType<IconProps>;
  export const Minimize2: ComponentType<IconProps>;
  export const Minus: ComponentType<IconProps>;
  export const Monitor: ComponentType<IconProps>;
  export const Play: ComponentType<IconProps>;
  export const RefreshCw: ComponentType<IconProps>;
  export const Settings: ComponentType<IconProps>;
  export const ShieldAlert: ComponentType<IconProps>;
  export const ShieldCheck: ComponentType<IconProps>;
  export const Sparkles: ComponentType<IconProps>;
  export const Stamp: ComponentType<IconProps>;
  export const UserRound: ComponentType<IconProps>;
  export const Video: ComponentType<IconProps>;
  export const Wrench: ComponentType<IconProps>;
  export const X: ComponentType<IconProps>;
}
