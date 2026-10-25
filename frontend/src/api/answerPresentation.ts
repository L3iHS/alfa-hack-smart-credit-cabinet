import type { Source } from './assistant';

function escapePattern(value: string) { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

export function presentAnswer(text: string, sources: Source[]): string {
  const annotations = new Set(sources.map(source => source.id));
  for (const source of sources) {
    let parsed: unknown;
    try { parsed = JSON.parse(source.text); } catch { continue; }
    const pending = [parsed];
    while (pending.length) {
      const value = pending.pop();
      if (Array.isArray(value)) pending.push(...value);
      else if (value && typeof value === 'object') {
        for (const [key, child] of Object.entries(value)) {
          if (/^[a-z][a-z0-9_]*$/i.test(key)) {
            annotations.add(key);
            if (key.endsWith('_kopecks')) annotations.add(key.slice(0, -'_kopecks'.length) + '_rubles');
            if (key.endsWith('_bps')) annotations.add(key.slice(0, -'_bps'.length) + '_percent');
          }
          if (child && typeof child === 'object') pending.push(child);
        }
      }
    }
  }
  // Убираем только точные пометки источника/поля; человеческие скобки и числа сохраняем.
  let answer = text.replace(/[ \t]*\(([^()\r\n]+)\)/g, (match, content: string) => {
    const annotation = content.trim().replace(/^`([^`]+)`$/, '$1');
    return annotations.has(annotation) ? '' : match;
  });
  for (const source of sources) {
    // Составной source ID заменяем целиком, не затрагивая UUID договора или часть другого ID.
    if (!/^[a-z][a-z0-9_.-]*(?::[a-z0-9_.-]+)+$/i.test(source.id)) continue;
    const pattern = new RegExp(`(^|[^a-z0-9_:.\\-])${escapePattern(source.id)}(?![a-z0-9_:\\-]|\\.[a-z0-9_])`, 'g');
    answer = answer.replace(pattern, (_match, prefix: string) => prefix + source.title);
  }
  return answer;
}
