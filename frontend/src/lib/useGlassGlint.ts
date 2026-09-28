import { useEffect } from "react";

/**
 * Mouse-tracked specular glint on glass panels.
 *
 * One delegated listener rather than one per panel: this page can show 60
 * cards at once, and 60 mousemove handlers firing at pointer rate is a lot of
 * work for a lighting effect. Coordinates are written on an animation frame so
 * several moves between paints collapse into one style write.
 *
 * Skipped entirely without a fine pointer — a touch screen has no hover, so
 * the glint would either never show or stick where a finger last was.
 */
export function useGlassGlint(): void {
  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!fine.matches || calm.matches) return;

    let frame = 0;
    let pending: { el: HTMLElement; x: number; y: number } | null = null;

    const flush = () => {
      frame = 0;
      if (!pending) return;
      const { el, x, y } = pending;
      el.style.setProperty("--mouse-x", `${x}px`);
      el.style.setProperty("--mouse-y", `${y}px`);
      pending = null;
    };

    const onMove = (event: MouseEvent) => {
      const panel = (event.target as HTMLElement | null)?.closest<HTMLElement>(
        ".card, .dialog",
      );
      if (!panel) return;
      const rect = panel.getBoundingClientRect();
      pending = {
        el: panel,
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      if (!frame) frame = requestAnimationFrame(flush);
    };

    document.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      document.removeEventListener("mousemove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
}
