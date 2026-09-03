import type { SVGProps } from "react";

const paths = {
  arrow: (
    <>
      <path d="M4 12h15" />
      <path d="m13 6 6 6-6 6" />
    </>
  ),
  arrowDown: (
    <>
      <path d="M12 4v15" />
      <path d="m6 13 6 6 6-6" />
    </>
  ),
  check: <path d="m5 12.5 4.4 4.3L19 6.6" />,
  close: <path d="m7 7 10 10M17 7 7 17" />,
  refresh: (
    <>
      <path d="M20 11a8.1 8.1 0 0 0-14.2-4.6L4 8.2" />
      <path d="M4 4.2v4h4" />
      <path d="M4 13a8.1 8.1 0 0 0 14.2 4.6l1.8-1.8" />
      <path d="M20 19.8v-4h-4" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.5 19 6v5.3c0 4.1-2.8 7.5-7 9.2-4.2-1.7-7-5.1-7-9.2V6z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  warning: (
    <>
      <path d="M12 4 21 20H3z" />
      <path d="M12 9.5V14M12 17h.01" />
    </>
  ),
  eye: (
    <>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  split: (
    <>
      <path d="M3 12h4l4-6h9" />
      <path d="M7 12h4l4 6h5" />
      <path d="m17 3 3 3-3 3" />
      <path d="m17 15 3 3-3 3" />
    </>
  ),
  scale: (
    <>
      <path d="M12 4v16" />
      <path d="M5 8h14" />
      <path d="m5 8-2.5 6a2.9 2.9 0 0 0 5 0Z" />
      <path d="m19 8-2.5 6a2.9 2.9 0 0 0 5 0Z" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.4V12l3.1 1.9" />
    </>
  ),
  stamp: (
    <>
      <rect x="3.6" y="4" width="16.8" height="16" rx="1.6" />
      <path d="M8 9.4h8M8 13h5" />
      <path d="M8 16.6h2" />
    </>
  ),
  pause: (
    <>
      <path d="M9.5 5.5v13" />
      <path d="M14.5 5.5v13" />
    </>
  ),
  play: <path d="M8 5.4 19 12 8 18.6z" />,
  spark: (
    <>
      <path d="M12 3.5 13.9 9l5.6 2-5.6 2-1.9 5.5L10.1 13 4.5 11l5.6-2z" />
    </>
  ),
  menu: (
    <>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </>
  ),
  route: (
    <>
      <circle cx="5.5" cy="18.5" r="2.3" />
      <circle cx="18.5" cy="5.5" r="2.3" />
      <path d="M7.8 18.5h6.4a4 4 0 0 0 0-8H9.5a4 4 0 0 1 0-8h0" />
    </>
  ),
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, ...rest }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      className="glyph"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {paths[name]}
    </svg>
  );
}
