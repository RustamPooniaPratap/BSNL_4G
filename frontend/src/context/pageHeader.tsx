/* eslint-disable react-refresh/only-export-components -- the provider, hook and heading belong together */
import { Children, createContext, isValidElement, useContext, useEffect, useState, type ReactNode } from 'react';

/**
 * The active page's title and reporting context, shown in the top application bar (AppLayout) instead of
 * a title card in the page. A page renders <PageHeading title=… subtitle=… />; when it has none, the bar
 * shows the route's title (lib/pageTitles). Outside AppLayout (e.g. in tests) PageHeading renders its own heading.
 */
export interface PageHeader { title: string; subtitle: string }

const Ctx = createContext<((header: PageHeader | null) => void) | null>(null);

export function usePageHeaderState() {
  return useState<PageHeader | null>(null);
}

export function PageHeaderProvider({ setHeader, children }: { setHeader: (header: PageHeader | null) => void; children: ReactNode }) {
  return <Ctx.Provider value={setHeader}>{children}</Ctx.Provider>;
}

/** Plain text of a node (strings, numbers, fragments, arrays), for the header and its change detection. */
export function textOf(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (isValidElement<{ children?: ReactNode }>(node)) return Children.toArray(node.props.children).map(textOf).join('');
  return '';
}

export function PageHeading({ title, subtitle }: { title: ReactNode; subtitle?: ReactNode }) {
  const setHeader = useContext(Ctx);
  const titleText = textOf(title).replace(/\s+/g, ' ').trim();
  const subtitleText = textOf(subtitle).replace(/\s+/g, ' ').trim();
  useEffect(() => {
    if (!setHeader) return;
    setHeader({ title: titleText, subtitle: subtitleText });
    return () => setHeader(null);
  }, [setHeader, titleText, subtitleText]);
  if (setHeader) return null;
  return (
    <header>
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
    </header>
  );
}
