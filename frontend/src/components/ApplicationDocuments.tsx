import { useState, type FormEvent } from "react";
import { api, ApiError, errorMessage } from "../api/client";
import type {
  Application,
  ApplicationDocument,
  DocumentType,
  SubmissionPolicy,
} from "../api/types";
import { dateTime, ErrorPanel, Loading, useResource } from "./shared";

export const documentLabels: Record<DocumentType, string> = {
  financial_statement: "Финансовая отчётность",
  equipment_invoice: "Счёт на оборудование",
};
export default function ApplicationDocuments({
  application,
  required,
  policy,
  locked,
  changed,
}: {
  application: Application;
  required: DocumentType[];
  policy: SubmissionPolicy | null;
  locked: boolean;
  changed: (version?: number) => Promise<void>;
}) {
  const { data, error, reload } = useResource(
    () =>
      api<{ items: ApplicationDocument[] }>(
        `/applications/${application.id}/documents`,
      ),
    `${application.id}-${application.version}`,
  );
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const [conflict, setConflict] = useState(false);
  const editable =
    application.available_actions.includes("upload_document") && !locked;
  async function mutation(action: () => Promise<number>) {
    if (busy) return;
    setBusy(true);
    setMutationError("");
    try {
      const version = await action();
      await changed(version);
      reload();
    } catch (error) {
      setMutationError(errorMessage(error));
      if (error instanceof ApiError && error.status === 409) setConflict(true);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    try {
      await changed();
      reload();
      setConflict(false);
      setMutationError("");
    } catch (error) {
      setMutationError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function upload(event: FormEvent<HTMLFormElement>, type: DocumentType) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || !file.size) {
      setMutationError("Выберите непустой файл");
      return;
    }
    if (!policy) return;
    if (file.size > policy.max_file_size_bytes) {
      setMutationError("Размер файла не должен превышать 10 МиБ");
      return;
    }
    if (!policy.accepted_content_types.includes(file.type)) {
      setMutationError("Выберите PDF, PNG или JPEG");
      return;
    }
    const params = new URLSearchParams({
      document_type: type,
      expected_version: String(application.version),
      filename: file.name,
    });
    await mutation(async () => {
      const result = await api<{
        document: ApplicationDocument;
        application_version: number;
      }>(`/applications/${application.id}/documents?${params}`, {
        method: "POST",
        rawBody: file,
      });
      form.reset();
      return result.application_version;
    });
  }
  function remove(document: ApplicationDocument) {
    void mutation(
      async () =>
        (
          await api<{ application_version: number }>(
            `/applications/${application.id}/documents/${document.id}?expected_version=${application.version}`,
            { method: "DELETE" },
          )
        ).application_version,
    );
  }
  return (
    <section
      className="panel documents-panel"
      aria-labelledby="documents-title"
    >
      <div className="section-top">
        <h2 id="documents-title">Документы</h2>
        <span className="muted">PDF, PNG, JPEG · до 10 МиБ</span>
      </div>
      {mutationError && (
        <div className="notice error" role="alert">
          <p>{mutationError}</p>
          {conflict && (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void refresh()}
            >
              Загрузить новую версию документов
            </button>
          )}
        </div>
      )}
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          {Object.entries(documentLabels)
            .filter(
              ([type]) =>
                required.includes(type as DocumentType) ||
                data.items.some((item) => item.document_type === type),
            )
            .map(([type, label]) => {
              const files = data.items.filter(
                (item) => item.document_type === type,
              );
              return (
                <div className="document-group" key={type}>
                  <div className="document-heading">
                    <h3>{label}</h3>
                    <span
                      className={files.length ? "document-present" : "muted"}
                    >
                      {files.length ? "Загружено" : "Нужен для отправки"}
                    </span>
                  </div>
                  {files.length > 0 && (
                    <ul className="document-list">
                      {files.map((file) => (
                        <li key={file.id}>
                          <div>
                            <a
                              className="text-link document-download"
                              href={`/api/v1/applications/${application.id}/documents/${file.id}`}
                              aria-label={`Скачать ${file.filename}`}
                            >
                              {file.filename}
                            </a>
                            <small>
                              {Math.max(1, Math.ceil(file.size_bytes / 1024))}{" "}
                              КБ · {dateTime(file.created_at)}
                            </small>
                          </div>
                          {editable && (
                            <button
                              className="document-remove"
                              aria-label={`Удалить ${file.filename}`}
                              disabled={busy || conflict}
                              onClick={() => remove(file)}
                            >
                              Удалить
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {editable && policy && (
                    <form
                      className="document-upload"
                      onSubmit={(event) =>
                        void upload(event, type as DocumentType)
                      }
                    >
                      <label className="field" htmlFor={`file-${type}`}>
                        <span className="sr-only">Файл: {label}</span>
                        <input
                          id={`file-${type}`}
                          name="file"
                          type="file"
                          accept={policy.accepted_content_types.join(",")}
                          disabled={busy || conflict}
                        />
                      </label>
                      <button
                        className="button secondary"
                        type="submit"
                        aria-label={`Загрузить: ${label}`}
                        disabled={busy || conflict}
                      >
                        {busy ? "Сохраняем…" : "Загрузить"}
                      </button>
                    </form>
                  )}
                </div>
              );
            })}
        </>
      )}
    </section>
  );
}
