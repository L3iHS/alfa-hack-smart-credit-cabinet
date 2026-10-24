import type { ReactNode } from 'react';

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) => part.startsWith('**') && part.endsWith('**') && part.length > 4
    ? <strong key={index}>{part.slice(2, -2)}</strong>
    : part);
}

// Поддерживаем только текстовые блоки. HTML, ссылки и изображения остаются обычным текстом.
export default function AnswerContent({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  const heading = (line: string) => /^#{1,6}\s+(.+)$/.exec(line);
  const bullet = (line: string) => /^\s*[-*+]\s+(.+)$/.exec(line);
  const numbered = (line: string) => /^\s*(\d+)[.)]\s+(.+)$/.exec(line);
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index++; continue; }
    const title = heading(line);
    if (title) { blocks.push(<h3 key={index}>{inline(title[1])}</h3>); index++; continue; }
    const unordered = bullet(line);
    const ordered = numbered(line);
    if (unordered || ordered) {
      const start = index;
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = ordered ? numbered(lines[index]) : bullet(lines[index]);
        if (!item) break;
        items.push(<li key={index}>{inline(item[ordered ? 2 : 1])}</li>);
        index++;
      }
      blocks.push(ordered ? <ol key={start} start={Number(ordered[1])}>{items}</ol> : <ul key={start}>{items}</ul>);
      continue;
    }
    const start = index;
    const paragraph = [line]; index++;
    while (index < lines.length && lines[index].trim() && !heading(lines[index]) && !bullet(lines[index]) && !numbered(lines[index])) {
      paragraph.push(lines[index]); index++;
    }
    blocks.push(<p key={start}>{inline(paragraph.join('\n'))}</p>);
  }
  return <div className="assistant-answer">{blocks}</div>;
}
