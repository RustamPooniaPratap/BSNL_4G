/** Rows of one page (1-based); the page is clamped so a shorter list never shows an empty page. */
export function pageOf<T>(rows: T[], page: number, size: number): { shown: T[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { shown: rows.slice((current - 1) * size, current * size), page: current, pages };
}
