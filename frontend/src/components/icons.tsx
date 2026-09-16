/** Icon set.
 *
 * Emoji were doing the work of icons and made the product look improvised:
 * they render differently on every platform, carry their own colour and never
 * align to a grid. These are hand-drawn on a 24px grid, single stroke weight,
 * `currentColor` only — so an icon inherits the exact colour and size of the
 * text next to it.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 20, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconTag = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.6 11.4V5a1.4 1.4 0 0 1 1.4-1.4h6.4a2 2 0 0 1 1.41.58l7 7a2 2 0 0 1 0 2.83l-5.99 5.99a2 2 0 0 1-2.83 0l-7-7a2 2 0 0 1-.39-.6" />
    <circle cx="8" cy="8" r="1.4" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10.5" cy="10.5" r="6.5" />
    <path d="m20 20-4.8-4.8" />
  </Svg>
);

export const IconBox = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.5 7.8v8.4a1.6 1.6 0 0 1-.83 1.4l-6.9 3.8a1.6 1.6 0 0 1-1.54 0l-6.9-3.8a1.6 1.6 0 0 1-.83-1.4V7.8" />
    <path d="m3.7 7.1 7.53-4.15a1.6 1.6 0 0 1 1.54 0L20.3 7.1 12 11.8Z" />
    <path d="M12 11.8V21" />
  </Svg>
);

export const IconWallet = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 8.2A2.2 2.2 0 0 1 5.7 6h12.6a2.2 2.2 0 0 1 2.2 2.2v8.6a2.2 2.2 0 0 1-2.2 2.2H5.7a2.2 2.2 0 0 1-2.2-2.2Z" />
    <path d="M3.5 10.2h17" />
    <path d="M16.5 14.6h1.6" />
  </Svg>
);

export const IconStar = ({ filled = false, ...p }: IconProps & { filled?: boolean }) => (
  <Svg {...p} fill={filled ? "currentColor" : "none"}>
    <path d="m12 3.6 2.6 5.27 5.82.85-4.21 4.1.99 5.79L12 16.87l-5.2 2.74.99-5.79-4.21-4.1 5.82-.85Z" />
  </Svg>
);

export const IconPlus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const IconPencil = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20h4l10.5-10.5a2.12 2.12 0 0 0-3-3L5 17v3Z" />
    <path d="m14.5 6.5 3 3" />
  </Svg>
);

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 6.5h15" />
    <path d="M9.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v1.5" />
    <path d="M6.5 6.5 7.3 19a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4l.8-12.5" />
  </Svg>
);

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />
  </Svg>
);

export const IconArrowUpRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7.5 16.5 16.5 7.5" />
    <path d="M9 7.5h7.5V15" />
  </Svg>
);

export const IconTruck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 7.2A1.2 1.2 0 0 1 4.7 6h8.1a1.2 1.2 0 0 1 1.2 1.2v8.3H3.5Z" />
    <path d="M14 10h3.1a1.6 1.6 0 0 1 1.34.72L20.5 14v1.5H14Z" />
    <circle cx="7.4" cy="17.4" r="1.9" />
    <circle cx="16.8" cy="17.4" r="1.9" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Svg>
);

export const IconPause = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.5 5.5v13M14.5 5.5v13" />
  </Svg>
);

export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.6v5M12 16.1h.01" />
  </Svg>
);

export const IconInbox = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 13.5h4l1.2 2.2h6.6l1.2-2.2h4" />
    <path d="M5.8 5.3h12.4l2.3 8.2v3.9a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2v-3.9Z" />
  </Svg>
);

/** Stop / cancel: the universal "no" ring, drawn on the same grid. */
export const IconCancel = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="m6.9 6.9 10.2 10.2" />
  </Svg>
);

export const IconReceipt = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3.5h12v17l-2-1.3-2 1.3-2-1.3-2 1.3-2-1.3-2 1.3Z" />
    <path d="M9 8.5h6M9 12.5h4" />
  </Svg>
);
