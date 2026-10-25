import type { Source } from '../../api/assistant';
import type { Catalog } from '../../api/types';
import { formatSource, visibleSources, type SourceGroup } from './formatSource';
function Group({ group }: { group: SourceGroup }) {
  return <div className="assistant-source-group">
    {group.label && <h4>{group.label}</h4>}
    {group.rows.length > 0 && <dl>{group.rows.map((row, index) => <div key={index}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>}
    {group.groups.map((child, index) => <Group key={index} group={child} />)}
  </div>;
}
export default function SourceDetails({ sources, catalog }: { sources: Source[]; catalog: Catalog }) {
  const visible = visibleSources(sources);
  if (!visible.length) return null;
  return <details className="assistant-sources"><summary>Источники ({visible.length})</summary>{visible.map((source, index) => {
    const content = formatSource(source.text, catalog);
    return <article key={`${source.id}:${index}`}><h3>{source.title}</h3>{content.text ? <p className="multiline">{content.text}</p> : <Group group={content} />}</article>;
  })}</details>;
}
