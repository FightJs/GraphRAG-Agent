function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function toSafeHtml(text: string): string {
  let html = escapeHtml(text)
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>')
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, '$1<em>$2</em>')
  html = html.replace(/\n/g, '<br/>')
  return html
}

export default function MarkdownText({ content, className }: { content: string; className?: string }) {
  return (
    <div
      className={className}
      // content is HTML-escaped before any tags are inserted
      dangerouslySetInnerHTML={{ __html: toSafeHtml(content) }}
    />
  )
}
