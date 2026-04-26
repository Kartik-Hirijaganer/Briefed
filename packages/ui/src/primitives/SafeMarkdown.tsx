import ReactMarkdown from 'react-markdown';
import rehypeSanitize, { defaultSchema, type Schema } from 'rehype-sanitize';
import { type JSX } from 'react';

/**
 * Allowlist used by {@link SafeMarkdown}. Whitelists exactly the elements
 * that the Briefed summary prompts can produce; everything else (script,
 * iframe, object, on* handlers, inline styles) is dropped at the
 * `rehype-sanitize` stage. Plan §11 + §19.11 Phase 8 require this guard.
 */
export const SAFE_MARKDOWN_SCHEMA: Schema = {
  ...defaultSchema,
  tagNames: ['p', 'strong', 'em', 'code', 'a', 'ul', 'ol', 'li', 'blockquote', 'br'],
  attributes: {
    a: ['href', 'title'],
  },
  protocols: {
    href: ['http', 'https', 'mailto'],
  },
  clobberPrefix: 'briefed-',
};

/**
 * Props for {@link SafeMarkdown}.
 */
export interface SafeMarkdownProps {
  /** Markdown source. May come from an LLM and is treated as untrusted. */
  readonly children: string;
  /** Optional className applied to the wrapping `<div>`. */
  readonly className?: string;
}

/**
 * Render LLM-produced markdown with a strict HTML allowlist.
 *
 * `react-markdown` parses the markdown source and `rehype-sanitize` runs
 * the resulting hast against {@link SAFE_MARKDOWN_SCHEMA}. Anchor tags
 * are coerced to `target="_blank" rel="noopener noreferrer"` so an LLM
 * cannot smuggle in a window-relationship escape.
 *
 * @param props - Component props.
 * @returns A `<div>` containing the sanitized markdown render.
 */
export function SafeMarkdown(props: SafeMarkdownProps): JSX.Element {
  return (
    <div className={props.className} data-testid="safe-markdown">
      <ReactMarkdown
        rehypePlugins={[[rehypeSanitize, SAFE_MARKDOWN_SCHEMA]]}
        skipHtml
        components={{
          a: ({ href, children, ...rest }) => (
            <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {props.children}
      </ReactMarkdown>
    </div>
  );
}
