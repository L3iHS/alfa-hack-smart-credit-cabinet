import type { AnswerOutput } from '../../api/assistant';
import type { Catalog } from '../../api/types';
import { dateTime } from '../shared';
import { formatSource, visibleSources, type SourceGroup } from './formatSource';

function sourceLines(group: SourceGroup, level = 3): string[] {
  return [
    ...(group.label ? [`${'#'.repeat(Math.min(level, 6))} ${group.label}`, ''] : []),
    ...group.rows.map(row => `- ${row.label}: ${row.value}`),
    ...group.groups.flatMap(child => ['', ...sourceLines(child, level + 1)]),
  ];
}

export function downloadSummary(answer: AnswerOutput, applicationNumber: string | undefined, catalog: Catalog) {
  const lines = [`# Сводка по заявке${applicationNumber ? ` № ${applicationNumber}` : ''}`, '',
    ...(answer.generated_at ? [`Сформировано: ${dateTime(answer.generated_at)}`, ''] : []), answer.answer, '', '## Источники', ''];
  for (const source of visibleSources(answer.sources)) {
    const content = formatSource(source.text, catalog);
    lines.push(`### ${source.title}`, '', ...(content.text ? [content.text] : sourceLines(content, 4)), '');
  }
  // Выгружаем текст: HTML модели не вставляется в DOM и не исполняется.
  const url = URL.createObjectURL(new Blob([lines.join('\n').replace(/</g, '&lt;').replace(/>/g, '&gt;')], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `summary-${applicationNumber || 'application'}-${(answer.generated_at || new Date().toISOString()).slice(0, 10)}.md`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
