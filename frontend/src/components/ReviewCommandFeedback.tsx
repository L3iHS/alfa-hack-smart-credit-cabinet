import type { ReviewCommand } from "./useReviewCommand";

export default function ReviewCommandFeedback({ command, labels = {} }: { command: ReviewCommand; labels?: Record<string, string> }) {
  return <>
    {command.error && <div className="notice error" role="alert">
      <p>{command.error}</p>
      {Object.entries(command.fields).map(([field, message]) => <p key={field}>{labels[field] || field}: {message}</p>)}
    </div>}
    {command.pending && !command.busy && <div className="notice" role="status">
      <p>Ответ не получен. Повтор сохранит исходные данные команды и не создаст второе действие</p>
      <button className="button primary" onClick={() => void command.send()}>Повторить действие</button>
    </div>}
    {(command.conflict || command.needsRefresh) && <div className="notice">
      {command.conflict && <p>Заявка изменилась. Ваш ввод сохранён; проверьте актуальное состояние перед новым действием</p>}
      <button className="button secondary" disabled={command.busy} onClick={() => void command.refresh()}>Загрузить актуальное состояние</button>
    </div>}
    {command.busy && <p role="status">Выполняем действие…</p>}
  </>;
}
