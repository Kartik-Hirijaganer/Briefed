// marks.jsx — Briefed logo marks. Each mark is a pure SVG parameterized by `c`
// (primary color). Secondary elements carry their own opacity so a single color
// reads correctly white-on-purple, purple-on-white, or mono-on-canvas.

function Mark({ id, c, size = 100 }) {
  const common = {
    viewBox: '0 0 100 100',
    width: size,
    height: size,
    fill: 'none',
    xmlns: 'http://www.w3.org/2000/svg',
  };
  switch (id) {
    // 1 · RANKED BRIEF — sorted, descending bars: must-read → waste.
    case 'ranked':
      return (
        <svg {...common}>
          <rect x="23" y="25" width="54" height="11" rx="5.5" fill={c} />
          <rect x="23" y="43" width="42" height="11" rx="5.5" fill={c} opacity="0.78" />
          <rect x="23" y="61" width="30" height="11" rx="5.5" fill={c} opacity="0.54" />
          <rect x="23" y="79" width="18" height="11" rx="5.5" fill={c} opacity="0.32" />
        </svg>
      );
    // 2 · MONOGRAM — typographic B in the brand display face.
    case 'mono':
      return (
        <svg {...common}>
          <text
            x="51"
            y="55"
            textAnchor="middle"
            dominantBaseline="central"
            fontFamily="'Inter Display','Inter Variable',sans-serif"
            fontWeight="700"
            fontSize="82"
            letterSpacing="-0.03em"
            fill={c}
          >
            B
          </text>
        </svg>
      );
    // 3 · DAYBREAK — sunrise over the baseline: the morning brief.
    case 'daybreak':
      return (
        <svg {...common}>
          <path d="M31 60 a19 19 0 0 1 38 0 Z" fill={c} />
          <rect x="18" y="64" width="64" height="8" rx="4" fill={c} />
          <rect x="30" y="79" width="40" height="7" rx="3.5" fill={c} opacity="0.5" />
        </svg>
      );
    // 4 · FOCUS — a brief framing the one signal worth your attention.
    case 'focus':
      return (
        <svg {...common}>
          <path
            d="M38 24 a30 30 0 0 0 0 52"
            stroke={c}
            strokeWidth="9"
            strokeLinecap="round"
            fill="none"
          />
          <path
            d="M62 24 a30 30 0 0 1 0 52"
            stroke={c}
            strokeWidth="9"
            strokeLinecap="round"
            fill="none"
          />
          <circle cx="50" cy="50" r="8" fill={c} />
        </svg>
      );
    // 5 · DISTILL — noise converging to a single distilled signal.
    case 'distill':
      return (
        <svg {...common}>
          <rect x="22" y="24" width="56" height="9" rx="4.5" fill={c} opacity="0.42" />
          <rect x="31" y="40" width="38" height="9" rx="4.5" fill={c} opacity="0.66" />
          <rect x="40" y="56" width="20" height="9" rx="4.5" fill={c} />
          <circle cx="50" cy="80" r="6" fill={c} />
        </svg>
      );
    default:
      return null;
  }
}

window.Mark = Mark;
