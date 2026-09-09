/**
 * The BidSense wordmark.
 *
 * Set as text with the "S" drawn inline, rather than shipped as the supplied
 * PNG or as one flat SVG. Three reasons, all of which bit in practice:
 *
 *   - the PNG carries a white background, which sits as a bright rectangle on
 *     the dark theme;
 *   - a raster wordmark softens at header size on a retina display;
 *   - and positioning glyphs by hand in SVG means guessing the font's metrics.
 *     The first attempt did exactly that and rendered "Bid S ense" with visible
 *     gaps. Letting the browser kern the text and inlining only the custom
 *     glyph is both simpler and correct.
 *
 * The lettering inherits `currentColor`, so the mark is dark ink on paper in
 * the light theme and warm off-white in the dark one with no second asset. The
 * "S" uses the accent token — the same blue the citation grammar uses, because
 * it carries the same promise.
 */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-baseline whitespace-nowrap leading-none ${className}`}
      aria-label="BidSense"
      role="img"
    >
      <span className="font-display font-semibold tracking-[-0.03em]">Bid</span>
      <AngularS className="mx-[0.02em] h-[0.78em] w-auto self-center" />
      <span className="font-display font-semibold tracking-[-0.03em]">ense</span>
    </span>
  );
}

/**
 * The one distinctive move in the mark: an S built from two angled strokes
 * meeting at a notch. No typeface has it, so it is drawn.
 */
function AngularS({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 34 44" className={className} fill="none" aria-hidden focusable="false">
      <path
        d="M33 0H12.6C6.4 0 1.4 4.6 1.4 10.3c0 3.9 2.4 7.4 6.1 9.1l16.8 7.9H7.2L0 44h21.4C27.6 44 32.6 39.4 32.6 33.7c0-3.9-2.4-7.4-6.1-9.1L9.7 16.7h16.1L33 0Z"
        fill="hsl(var(--accent))"
      />
      {/* The notch: a sliver of the page ground cutting the stroke, which is
          what stops the S reading as a plain lightning bolt. */}
      <path d="M13.2 19.4 22 23.5l-1.9 3.1-8.8-4.1 1.9-3.1Z" fill="hsl(var(--surface))" />
    </svg>
  );
}

/** The mark alone, for a favicon-sized slot. */
export function LogoMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="BidSense">
      <rect width="32" height="32" rx="3" fill="hsl(var(--accent))" />
      <path
        d="M24.5 5H12.9c-3.4 0-6.2 2.6-6.2 5.8 0 2.2 1.3 4.2 3.4 5.1l9.4 4.4H9.6L6.5 27h11.6c3.4 0 6.2-2.6 6.2-5.8 0-2.2-1.3-4.2-3.4-5.1l-9.4-4.4h9.9L24.5 5Z"
        fill="hsl(var(--accent-fg))"
      />
    </svg>
  );
}
