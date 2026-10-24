import type { Source } from '../../api/assistant';
import type { Catalog } from '../../api/types';
import { formatSource } from './formatSource';
export default function SourceDetails({ sources, catalog }: { sources: Source[]; catalog: Catalog }) {
  if (!sources.length) return null;
  return <details className="assistant-sources"><summary>Источники ({sources.length})</summary>{sources.map((source, index) => {
    const content = formatSource(source.text, catalog);
    return <article key={`${source.id}:${index}`}><h3>{source.title}</h3>{content.rows ? <dl>{content.rows.map((row, rowIndex) => <div key={rowIndex}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl> : <p className="multiline">{content.text}</p>}</article>;
  })}</details>;
}
