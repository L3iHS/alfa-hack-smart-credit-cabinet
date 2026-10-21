# Сторонние компоненты

Инвентаризация базовых компонентов на 20 октября 2026 года; ML extra дополнен 22 октября 2026 года. Версии Python сверены с `backend/uv.lock`, лицензии — с метаданными установленных locked-пакетов; версии и SPDX-обозначения npm взяты из `frontend/package-lock.json`. Ссылки PyPI ведут на конкретные выпуски. Исходные LICENSE/NOTICE компонентов остаются частью их пакетов; этот перечень не заменяет их тексты.

## Backend и инструменты проверки

| Компонент | Версия | Лицензия в метаданных |
| --- | --- | --- |
| [alembic](https://pypi.org/project/alembic/1.15.2/) | 1.15.2 | MIT |
| [annotated-doc](https://pypi.org/project/annotated-doc/0.0.5/) | 0.0.5 | MIT |
| [annotated-types](https://pypi.org/project/annotated-types/0.8.0/) | 0.8.0 | MIT |
| [anyio](https://pypi.org/project/anyio/4.15.1/) | 4.15.1 | MIT |
| [argon2-cffi](https://pypi.org/project/argon2-cffi/23.1.0/) | 23.1.0 | MIT |
| [argon2-cffi-bindings](https://pypi.org/project/argon2-cffi-bindings/26.1.0/) | 26.1.0 | MIT |
| [certifi](https://pypi.org/project/certifi/2026.10.19/) | 2026.10.19 | MPL-2.0 |
| [cffi](https://pypi.org/project/cffi/2.1.1/) | 2.1.1 | MIT-0 |
| [click](https://pypi.org/project/click/8.5.0/) | 8.5.0 | BSD-3-Clause |
| [fastapi](https://pypi.org/project/fastapi/0.151.0/) | 0.151.0 | MIT |
| [greenlet](https://pypi.org/project/greenlet/3.5.6/) | 3.5.6 | MIT AND PSF-2.0 |
| [h11](https://pypi.org/project/h11/0.16.0/) | 0.16.0 | MIT |
| [httpcore](https://pypi.org/project/httpcore/1.0.9/) | 1.0.9 | BSD-3-Clause |
| [httpx](https://pypi.org/project/httpx/0.28.1/) | 0.28.1 | BSD-3-Clause |
| [idna](https://pypi.org/project/idna/3.20/) | 3.20 | BSD-3-Clause |
| [iniconfig](https://pypi.org/project/iniconfig/2.3.1/) | 2.3.1 | MIT |
| [Mako](https://pypi.org/project/Mako/1.4.3/) | 1.4.3 | MIT |
| [MarkupSafe](https://pypi.org/project/MarkupSafe/3.0.4/) | 3.0.4 | BSD-3-Clause |
| [opentelemetry-api](https://pypi.org/project/opentelemetry-api/1.45.1/) | 1.45.1 | Apache-2.0 |
| [packaging](https://pypi.org/project/packaging/26.3/) | 26.3 | Apache-2.0 OR BSD-2-Clause |
| [pillow](https://pypi.org/project/pillow/13.0.0/) | 13.0.0 | MIT-CMU |
| [pluggy](https://pypi.org/project/pluggy/1.7.0/) | 1.7.0 | MIT |
| [psycopg](https://pypi.org/project/psycopg/3.2.6/) | 3.2.6 | LGPLv3 |
| [psycopg-binary](https://pypi.org/project/psycopg-binary/3.2.6/) | 3.2.6 | LGPLv3 |
| [pwdlib](https://pypi.org/project/pwdlib/0.2.1/) | 0.2.1 | MIT |
| [pycparser](https://pypi.org/project/pycparser/3.11/) | 3.11 | BSD-3-Clause |
| [pydantic](https://pypi.org/project/pydantic/2.14.1/) | 2.14.1 | MIT |
| [pydantic-settings](https://pypi.org/project/pydantic-settings/2.8.1/) | 2.8.1 | MIT |
| [pydantic_core](https://pypi.org/project/pydantic_core/2.50.1/) | 2.50.1 | MIT |
| [pypdf](https://pypi.org/project/pypdf/6.21.1/) | 6.21.1 | BSD-3-Clause |
| [pytest](https://pypi.org/project/pytest/8.3.5/) | 8.3.5 | MIT |
| [python-dotenv](https://pypi.org/project/python-dotenv/1.2.4/) | 1.2.4 | BSD-3-Clause |
| [SQLAlchemy](https://pypi.org/project/SQLAlchemy/2.0.40/) | 2.0.40 | MIT |
| [starlette](https://pypi.org/project/starlette/0.52.1/) | 0.52.1 | BSD-3-Clause |
| [typing-inspection](https://pypi.org/project/typing-inspection/0.4.4/) | 0.4.4 | MIT |
| [typing_extensions](https://pypi.org/project/typing_extensions/4.16.0/) | 4.16.0 | PSF-2.0 |
| [uvicorn](https://pypi.org/project/uvicorn/0.34.2/) | 0.34.2 | BSD-3-Clause |

Pillow использует [MIT-CMU](https://github.com/python-pillow/Pillow/blob/main/LICENSE), а не обычную MIT: PIL © 1997–2011 Secret Labs AB, © 1995–2011 Fredrik Lundh and contributors; Pillow © 2010 Jeffrey 'Alex' Clark and contributors. Psycopg и бинарный пакет используют [LGPLv3](https://github.com/psycopg/psycopg/blob/3.2.6/psycopg/LICENSE.txt). Бинарные колёса Pillow и psycopg-binary также включают нативные компоненты. Лицензионные файлы самих пакетов установлены в `pillow-13.0.0.dist-info/licenses/LICENSE` и `psycopg_binary-3.2.6.dist-info/LICENSE.txt`; состав нативных компонентов зависит от платформенного колеса. При отдельном распространении таких колёс нужно учитывать их вложенные компоненты и сохранять исходные уведомления поставки. Certifi содержит набор сертификатов Mozilla под MPL-2.0.

## Offline ML и построение отчётов

Эти пакеты устанавливаются только с extra `ml` / `INSTALL_ML=true`. Обычный backend использует собственный JSON и stdlib inference; numpy, scikit-learn и CatBoost для обработки заявок не требуются. Версии сверены с lock-файлом и метаданными установленного Linux/aarch64-образа; ссылки ведут на официальные лицензии проектов. Для четырёх основных пакетов проверены закреплённые релизы, для остальных — исходные лицензии и метаданные соответствующих установленных версий.

| Компонент | Версия | Основная лицензия / официальный источник |
| --- | --- | --- |
| NumPy | 2.2.6 | [BSD-3-Clause](https://github.com/numpy/numpy/blob/v2.2.6/LICENSE.txt) |
| pandas | 2.3.3 | [BSD-3-Clause](https://github.com/pandas-dev/pandas/blob/v2.3.3/LICENSE) |
| scikit-learn | 1.7.2 | [BSD-3-Clause](https://github.com/scikit-learn/scikit-learn/blob/1.7.2/COPYING) |
| CatBoost | 1.2.8 | [Apache-2.0](https://github.com/catboost/catboost/blob/v1.2.8/LICENSE) |
| Matplotlib | 3.10.7 | [Matplotlib License, основана на PSF; включены исторические лицензии](https://github.com/matplotlib/matplotlib/blob/v3.10.7/LICENSE/LICENSE) |
| joblib | 1.5.2 | [BSD-3-Clause](https://github.com/joblib/joblib/blob/1.5.2/LICENSE.txt) |
| threadpoolctl | 3.6.0 | [BSD-3-Clause](https://github.com/joblib/threadpoolctl/blob/3.6.0/LICENSE) |
| SciPy | 1.18.1 | [BSD-3-Clause](https://github.com/scipy/scipy/blob/v1.18.1/LICENSE.txt) |
| contourpy | 1.4.0 | [BSD-3-Clause](https://github.com/contourpy/contourpy/blob/v1.4.0/LICENSE) |
| cycler | 0.12.1 | [BSD-3-Clause](https://github.com/matplotlib/cycler/blob/v0.12.1/LICENSE) |
| fonttools | 4.67.0 | [MIT](https://github.com/fonttools/fonttools/blob/4.67.0/LICENSE) |
| graphviz, Python-пакет | 0.21 | [MIT](https://github.com/xflr6/graphviz/blob/0.21/LICENSE.txt) |
| kiwisolver | 1.5.1 | [BSD-3-Clause](https://github.com/nucleic/kiwi/blob/1.5.1/LICENSE) |
| narwhals | 2.27.1 | [MIT](https://github.com/narwhals-dev/narwhals/blob/main/LICENSE.md) |
| plotly | 7.1.0 | [MIT](https://github.com/plotly/plotly.py/blob/v7.1.0/LICENSE.txt) |
| pyparsing | 3.3.3 | [MIT](https://github.com/pyparsing/pyparsing/blob/master/LICENSE) |
| python-dateutil | 2.9.0.post0 | [Apache-2.0 и BSD-3-Clause для исторических частей](https://github.com/dateutil/dateutil/blob/2.9.0.post0/LICENSE) |
| pytz | 2026.5 | [MIT](https://github.com/stub42/pytz/blob/master/LICENSE.txt) |
| six | 1.17.0 | [MIT](https://github.com/benjaminp/six/blob/1.17.0/LICENSE) |
| tzdata | 2026.5 | [Apache-2.0 для пакета; данные IANA в общественном достоянии](https://github.com/python/tzdata/blob/master/LICENSE) |

NumPy/SciPy и другие бинарные колёса могут содержать дополнительные библиотеки с отдельными лицензиями (например BLAS/LAPACK, runtime компилятора). Matplotlib также поставляет шрифты и вспомогательные материалы с отдельными уведомлениями. Полные `LICENSE`/`NOTICE`, лицензии вложенных компонентов и copyright сохраняются в исходных пакетах и `.dist-info/licenses`; этот перечень основной лицензии Python-пакета не заменяет их. Python-пакет graphviz не означает поставку системного Graphviz. Платформенные колёса и их состав могут различаться.

## Frontend и инструменты сборки/браузерной проверки

| npm-пакет | Версия | Лицензия в lock-файле |
| --- | --- | --- |
| `@babel/code-frame` | 7.29.7 | MIT |
| `@babel/compat-data` | 7.29.7 | MIT |
| `@babel/core` | 7.29.7 | MIT |
| `@babel/generator` | 7.29.8 | MIT |
| `@babel/helper-compilation-targets` | 7.29.7 | MIT |
| `@babel/helper-globals` | 7.29.7 | MIT |
| `@babel/helper-module-imports` | 7.29.7 | MIT |
| `@babel/helper-module-transforms` | 7.29.7 | MIT |
| `@babel/helper-plugin-utils` | 7.29.7 | MIT |
| `@babel/helper-string-parser` | 7.29.7 | MIT |
| `@babel/helper-validator-identifier` | 7.29.7 | MIT |
| `@babel/helper-validator-option` | 7.29.7 | MIT |
| `@babel/helpers` | 7.29.10 | MIT |
| `@babel/parser` | 7.29.9 | MIT |
| `@babel/plugin-transform-react-jsx-self` | 7.29.7 | MIT |
| `@babel/plugin-transform-react-jsx-source` | 7.29.7 | MIT |
| `@babel/template` | 7.29.7 | MIT |
| `@babel/traverse` | 7.29.10 | MIT |
| `@babel/types` | 7.29.8 | MIT |
| `@jridgewell/gen-mapping` | 0.3.13 | MIT |
| `@jridgewell/remapping` | 2.3.5 | MIT |
| `@jridgewell/resolve-uri` | 3.1.2 | MIT |
| `@jridgewell/sourcemap-codec` | 1.6.0 | MIT |
| `@jridgewell/trace-mapping` | 0.3.31 | MIT |
| `@napi-rs/lzma-linux-x64-gnu` | 1.5.1 | MIT |
| `@playwright/test` | 1.56.1 | Apache-2.0 |
| `@types/babel__core` | 7.20.5 | MIT |
| `@types/babel__generator` | 7.27.0 | MIT |
| `@types/babel__template` | 7.4.4 | MIT |
| `@types/babel__traverse` | 7.28.0 | MIT |
| `@types/estree` | 1.0.9 | MIT |
| `@types/react` | 19.0.12 | MIT |
| `@types/react-dom` | 19.0.4 | MIT |
| `@vitejs/plugin-react` | 4.4.1 | MIT |
| `baseline-browser-mapping` | 2.11.30 | Apache-2.0 |
| `browserslist` | 4.29.4 | MIT |
| `caniuse-lite` | 1.0.30001817 | CC-BY-4.0 |
| `convert-source-map` | 2.0.0 | MIT |
| `cookie` | 1.1.1 | MIT |
| `csstype` | 3.2.3 | MIT |
| `debug` | 4.4.3 | MIT |
| `electron-to-chromium` | 1.5.461 | ISC |
| `esbuild` | 0.25.12 | MIT |
| `escalade` | 3.2.0 | MIT |
| `fdir` | 6.5.0 | MIT |
| `fsevents` | 2.3.3 | MIT |
| `gensync` | 1.0.0-beta.2 | MIT |
| `js-tokens` | 4.0.0 | MIT |
| `jsesc` | 3.1.0 | MIT |
| `json5` | 2.2.3 | MIT |
| `lru-cache` | 5.1.1 | ISC |
| `ms` | 2.1.3 | MIT |
| `nanoid` | 3.3.20 | MIT |
| `node-releases` | 2.0.59 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 4.0.7 | MIT |
| `playwright` | 1.56.1 | Apache-2.0 |
| `playwright-core` | 1.56.1 | Apache-2.0 |
| `playwright/node_modules/fsevents` | 2.3.2 | MIT |
| `postcss` | 8.5.31 | MIT |
| `react` | 19.0.0 | MIT |
| `react-dom` | 19.0.0 | MIT |
| `react-refresh` | 0.17.0 | MIT |
| `react-router` | 7.18.4 | MIT |
| `react-router-dom` | 7.18.4 | MIT |
| `rollup` | 4.64.12 | MIT |
| `scheduler` | 0.25.0 | MIT |
| `semver` | 6.3.1 | ISC |
| `set-cookie-parser` | 2.7.2 | MIT |
| `source-map-js` | 1.2.2 | BSD-3-Clause |
| `tinyglobby` | 0.2.17 | MIT |
| `typescript` | 5.8.3 | Apache-2.0 |
| `update-browserslist-db` | 1.3.4 | MIT |
| `vite` | 6.4.4 | MIT |
| `yallist` | 3.1.1 | ISC |

Платформенные пакеты `@esbuild/*` версии 0.25.12 и `@rollup/rollup-*` версии 4.64.12 имеют MIT по метаданным lock-файла; конкретная платформа выбирается npm. Полный перечень вариантов и контрольные суммы находятся в `frontend/package-lock.json`. Для `react`/`react-dom`/`scheduler` правообладатель — Meta Platforms, Inc. and affiliates; [исходный текст MIT](https://github.com/facebook/react/blob/v19.0.0/LICENSE). Файлы `LICENSE`, `NOTICE` и встроенные лицензионные комментарии npm-пакетов сохраняют исходные атрибуции. Данные caniuse-lite распространяются по CC-BY-4.0; [проект и источники данных](https://github.com/browserslist/caniuse-lite).

Playwright устанавливает браузер отдельно от npm-пакета. Chromium содержит собственные сторонние компоненты и уведомления (`chrome://credits`); [лицензия Chromium](https://chromium.googlesource.com/chromium/src/+/main/LICENSE). Браузер используется для проверки и не включается во frontend-образ.

## Среда контейнеров

| Компонент | Закреплённая версия | Основная лицензия и источник |
| --- | --- | --- |
| Python | 3.12.10 | [PSF License и история лицензий](https://docs.python.org/3.12/license.html) |
| uv | 0.6.14 | [MIT](https://github.com/astral-sh/uv/blob/0.6.14/LICENSE-MIT) или [Apache-2.0](https://github.com/astral-sh/uv/blob/0.6.14/LICENSE-APACHE) |
| Node.js, только стадия сборки | 22.15.0 | [MIT и уведомления встроенных компонентов](https://github.com/nodejs/node/blob/v22.15.0/LICENSE) |
| PostgreSQL | 17.4-alpine | [PostgreSQL License](https://www.postgresql.org/about/licence/) |
| nginx | 1.28.0-alpine | [BSD-2-Clause](https://nginx.org/LICENSE) |
| Caddy, серверное дополнение | 2.11.7-alpine | [Apache-2.0](https://github.com/caddyserver/caddy/blob/v2.11.7/LICENSE) |

Образы Debian/Alpine включают дополнительные системные пакеты с собственными лицензиями; состав зависит от digest образа, а теги не фиксируют все системные ревизии. Их уведомления поставляются в образах (`/usr/share/doc`, сведения пакетного менеджера); этот список описывает зависимости приложения и основные runtime-компоненты, а не полную инвентаризацию ОС.

## Данные и визуальные материалы

Компании, профили, показатели и проверочные документы демонстрационные. Поставляется собственная модель команды `logistic-risk-v1`: JSON коэффициентов LogisticRegression и train-преобразований в `backend/app/risk/models/logistic-risk-v1.json`. Она обучена командой на собственных 10 000 синтетических компаний, без внешних pretrained-весов и реальных банковских данных. Её происхождение, схема и контрольная сумма зафиксированы в поставке; качество описано в [ML-эксперименте](docs/ml-training.md). Данные обучения и альтернативные offline-модели не входят в обычный образ. Реальные внешние ФНС/БКИ, OCR, LLM-модели и LLM API не поставляются. Интерфейс использует системные шрифты; импортированных шрифтов, стоковых фотографий и сторонних наборов иконок в frontend нет.
