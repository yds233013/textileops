/**
 * A small, consistent icon set: 20-unit grid, 1.6 stroke, round joins.
 * Inline SVG so the product carries no icon dependency and nothing loads late.
 * Every icon is decorative (aria-hidden); meaning always lives in text.
 */
import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 16, children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconGauge = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 14a6.5 6.5 0 1 1 13 0" />
    <path d="M10 14l3-4.5" />
    <circle cx="10" cy="14" r="1" />
  </Icon>
);
export const IconAlert = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 3.2 17.5 16H2.5L10 3.2Z" />
    <path d="M10 8.5v3.2M10 13.9v.1" />
  </Icon>
);
export const IconCheckCircle = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="10" r="7" />
    <path d="m7 10.2 2 2 4-4.2" />
  </Icon>
);
export const IconClipboard = (p: IconProps) => (
  <Icon {...p}>
    <rect x="4.5" y="3.5" width="11" height="14" rx="1.5" />
    <path d="M7.5 3.5V2.8h5v.7M7.5 8.5h5M7.5 11.5h5M7.5 14.5h3" />
  </Icon>
);
export const IconTruck = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2.5 5.5h9v8h-9zM11.5 8.5h3l3 3v2h-6" />
    <circle cx="6" cy="14.5" r="1.5" />
    <circle cx="14.5" cy="14.5" r="1.5" />
  </Icon>
);
export const IconInbound = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 7.5 10 3.5l7 4v8l-7 4-7-4z" />
    <path d="M3 7.5l7 4 7-4M10 11.5v8" />
  </Icon>
);
export const IconBuilding = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 17V8l4.5-2.5V8L12 5.5V8l5-2.5V17z" />
    <path d="M2 17h16M6.5 13h1M10.5 13h1M14.5 13h1" />
  </Icon>
);
export const IconStock = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="10.5" width="6" height="6" rx="1" />
    <rect x="11" y="10.5" width="6" height="6" rx="1" />
    <rect x="7" y="3.5" width="6" height="6" rx="1" />
  </Icon>
);
export const IconLayers = (p: IconProps) => (
  <Icon {...p}>
    <path d="m10 3 7 3.8-7 3.8-7-3.8z" />
    <path d="m3 10.2 7 3.8 7-3.8M3 13.6l7 3.8 7-3.8" />
  </Icon>
);
export const IconSpool = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 3.5h10M5 16.5h10" />
    <path d="M6.5 3.5v13M13.5 3.5v13" />
    <path d="M6.5 6.5 13.5 8M6.5 9.5l7 1.5M6.5 12.5l7 1.5" />
  </Icon>
);
export const IconShield = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 2.8 16 5v4.6c0 3.7-2.6 6.4-6 7.6-3.4-1.2-6-3.9-6-7.6V5z" />
    <path d="m7.4 9.8 1.8 1.8 3.4-3.6" />
  </Icon>
);
export const IconInbox = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 11.5 5 4.5h10l2 7v4H3z" />
    <path d="M3 11.5h4l1 2h4l1-2h4" />
  </Icon>
);
export const IconMerge = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="6" cy="4.5" r="1.7" />
    <circle cx="6" cy="15.5" r="1.7" />
    <circle cx="14.5" cy="10" r="1.7" />
    <path d="M6 6.2v7.6M6 8.5c0 1.5 1.5 1.5 3 1.5h3.8" />
  </Icon>
);
export const IconHistory = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 10a6.5 6.5 0 1 0 2-4.7" />
    <path d="M3 3.5v3h3M10 6.5V10l2.5 1.5" />
  </Icon>
);
export const IconChart = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 16.5h14M5.5 13.5v-3M9 13.5v-7M12.5 13.5V9M16 13.5V5" />
  </Icon>
);
export const IconPlay = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="10" r="7" />
    <path d="m8.3 7.3 4.4 2.7-4.4 2.7z" />
  </Icon>
);
export const IconSettings = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="10" r="2.4" />
    <path d="M10 2.8v2M10 15.2v2M2.8 10h2M15.2 10h2M4.9 4.9l1.4 1.4M13.7 13.7l1.4 1.4M4.9 15.1l1.4-1.4M13.7 6.3l1.4-1.4" />
  </Icon>
);
export const IconSearch = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="9" cy="9" r="5.2" />
    <path d="m13 13 3.8 3.8" />
  </Icon>
);
export const IconChevronRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="m8 5 5 5-5 5" />
  </Icon>
);
export const IconChevronDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 8 5 5 5-5" />
  </Icon>
);
export const IconArrowRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 10h12M11.5 5.5 16 10l-4.5 4.5" />
  </Icon>
);
export const IconX = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 5 10 10M15 5 5 15" />
  </Icon>
);
export const IconMenu = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 5.5h14M3 10h14M3 14.5h14" />
  </Icon>
);
export const IconCalculator = (p: IconProps) => (
  <Icon {...p}>
    <rect x="4" y="2.8" width="12" height="14.4" rx="1.5" />
    <path d="M7 6h6M7 10h.1M10 10h.1M13 10h.1M7 13.5h.1M10 13.5h.1M13 13.5h.1" />
  </Icon>
);
export const IconQuote = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 12.5c0-3.5 1.5-5.5 4-6.5M11 12.5c0-3.5 1.5-5.5 4-6.5" />
    <path d="M4 12.5h3v3H4zM11 12.5h3v3h-3z" />
  </Icon>
);
export const IconModel = (p: IconProps) => (
  <Icon {...p}>
    <rect x="4.5" y="4.5" width="11" height="11" rx="2" />
    <path d="M8 1.8v2.7M12 1.8v2.7M8 15.5v2.7M12 15.5v2.7M1.8 8h2.7M1.8 12h2.7M15.5 8h2.7M15.5 12h2.7" />
    <path d="M8 8h4v4H8z" />
  </Icon>
);
export const IconUser = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="7" r="3" />
    <path d="M4 17c.8-3 3.2-4.5 6-4.5s5.2 1.5 6 4.5" />
  </Icon>
);
export const IconClock = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="10" r="7" />
    <path d="M10 6v4l2.5 1.5" />
  </Icon>
);
export const IconLogout = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 4H5a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 5 16h3M12.5 13.5 16 10l-3.5-3.5M16 10H8" />
  </Icon>
);
export const IconRefresh = (p: IconProps) => (
  <Icon {...p}>
    <path d="M16 4.5v3.5h-3.5M4 15.5V12h3.5" />
    <path d="M15.3 8A6 6 0 0 0 4.9 6.3M4.7 12a6 6 0 0 0 10.4 1.7" />
  </Icon>
);
export const IconUpload = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 13V3.5M6 7.5l4-4 4 4M3.5 13v2.5A1.5 1.5 0 0 0 5 17h10a1.5 1.5 0 0 0 1.5-1.5V13" />
  </Icon>
);
export const IconInfo = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="10" cy="10" r="7" />
    <path d="M10 9v4.5M10 6.5v.1" />
  </Icon>
);

/** The mark: warp and weft — two threads crossing, which is what cloth is. */
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden focusable={false}>
      <rect width="24" height="24" rx="6" fill="#30398f" />
      <path d="M6 9h12M6 15h12" stroke="#bcc5ef" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M9 6v4.2M9 13.8V18M15 6v1.2M15 10.8v2.4M15 16.8V18" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}
