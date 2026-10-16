# ARVEN на сервере (VPS) — пошаговая инструкция

На сервере ARVEN работает круглосуточно и не зависит от ноутбука, его сна и домашнего интернета. Это всё так же
система поддержки решений: она даёт сигналы и не выставляет ордера.

Файлы для сервера лежат в `deploy/linux/`: `arven-live.service` и `arven-web.service`. Это сервисы systemd. Они
сами перезапускают процессы при сбое и после перезагрузки сервера.

## 0. Какой сервер нужен

| Параметр | Значение |
|---|---|
| Система | **Ubuntu 24.04 LTS** (ниже) или Debian 13 (там Python 3.13 уже есть) |
| Память | **4 ГБ** (2 ГБ мало: тик загружает всю историю 15m-свечей и признаки) |
| Процессор | 2 vCPU |
| Диск | 40 ГБ |
| Регион | **Европа** (Германия, Нидерланды, Финляндия). **Не США:** Binance блокирует адреса из США |

## 1. Первый вход и пользователь

С ноутбука (PowerShell) подключитесь к серверу. IP и пароль root даёт провайдер.

```
ssh root@IP_СЕРВЕРА
```

На сервере выполните:

```bash
apt update && apt -y upgrade
adduser --disabled-password --gecos "" arven
mkdir -p /opt/arven && chown arven:arven /opt/arven
ufw allow OpenSSH && ufw --force enable          # наружу открыт только SSH
timedatectl                                       # "System clock synchronized: yes" - время точное
```

**Проверка Binance:**

```bash
curl -s https://fapi.binance.com/fapi/v1/time
```

Ответ должен быть вида `{"serverTime":...}`. Если пришла ошибка `451` или пустой ответ, Binance недоступен из этого
региона: смените регион сервера.

## 2. Python 3.13

```bash
apt -y install software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt update && apt -y install python3.13 python3.13-venv
```

На Debian 13 достаточно `apt -y install python3 python3-venv`.

## 3. Перенос кода и данных с ноутбука

На ноутбуке (PowerShell, папка проекта):

```powershell
git archive --format=zip -o arven-code.zip HEAD                  # код из git (без .env и data)
.venv\Scripts\python.exe -m arven backup --with-db               # база, сигналы, состояние -> data\backups\arven-....zip
Compress-Archive -Path web\dist -DestinationPath web-dist.zip -Force   # собранный сайт
scp arven-code.zip web-dist.zip data\backups\arven-<время>.zip root@IP_СЕРВЕРА:/opt/arven/
```

На сервере:

```bash
apt -y install unzip
cd /opt/arven
unzip -o arven-code.zip
unzip -o arven-*Z.zip                 # кладёт data/ и config/ на место
mkdir -p web && unzip -o web-dist.zip -d web/
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
chown -R arven:arven /opt/arven
```

## 4. Секреты: `.env` на сервере

Секреты вводятся вручную на сервере. В архивы и в git они не попадают.

```bash
sudo -u arven nano /opt/arven/.env
```

Впишите те же две строки, что на ноутбуке:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_IDS=...
```

Затем выполните:

```bash
chmod 600 /opt/arven/.env
cd /opt/arven && sudo -u arven .venv/bin/python -m arven telegram test   # тестовое сообщение должно прийти
```

## 5. Сначала выключить ноутбук, потом включить сервер

**Важно:** если ARVEN работает в двух местах сразу, каждый сигнал придёт в Telegram дважды. Поэтому сначала
останавливаем ноутбук.

На ноутбуке (PowerShell):

```powershell
New-Item data\live\live.stop -ItemType File      # процесс завершит текущий проход и выйдет
Disable-ScheduledTask -TaskName "ARVEN Live"
Disable-ScheduledTask -TaskName "ARVEN Web"
```

Сделайте резервную копию (шаг 3) **после** остановки, чтобы на сервер ушло последнее состояние.

На сервере:

```bash
cp /opt/arven/deploy/linux/arven-live.service /opt/arven/deploy/linux/arven-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now arven-live arven-web
systemctl status arven-live --no-pager
tail -3 /opt/arven/data/live/live_process.log      # "Telegram: N chat(s), sending, token set"
```

Через минуту в Telegram придёт сообщение «live loop started». Процесс сам догонит время, пока ARVEN был выключен.

## 6. Сайт с ноутбука (безопасно, через SSH-туннель)

Сайт на сервере слушает только `127.0.0.1` и не открыт в интернет. С ноутбука:

```powershell
ssh -N -L 8000:127.0.0.1:8000 arven@IP_СЕРВЕРА
```

Пока команда работает, сайт открывается на ноутбуке как обычно: http://127.0.0.1:8000. Чтобы входить пользователем
`arven` без пароля, добавьте свой SSH-ключ в `/home/arven/.ssh/authorized_keys`.

Открывать сайт для всего интернета без пароля и HTTPS **не надо**. Если это понадобится, это отдельная настройка
(reverse proxy с паролем и сертификатом).

## 7. Повседневные команды на сервере

| Что | Команда |
|---|---|
| жив ли процесс | `cd /opt/arven && .venv/bin/python -m arven live heartbeat` |
| сводка стратегий | `.venv/bin/python -m arven live status` |
| журнал | `tail -f data/live/live.jsonl` |
| остановить | `touch data/live/live.stop` (процесс завершит проход и выйдет; пока файл есть, каждый перезапуск systemd сразу завершается) |
| запустить снова | `rm data/live/live.stop && systemctl restart arven-live` |
| перезапуск после изменения `config/live.yaml` | `systemctl restart arven-live` |
| резервная копия | создаётся каждый день в 01:00 UTC в `data/backups` (последние 7). Время от времени копируйте её себе: `scp arven@IP:/opt/arven/data/backups/<файл> .` |

## 8. Обновление кода

На ноутбуке соберите новый `arven-code.zip` (`git archive`, шаг 3) и скопируйте на сервер. Затем на сервере:

```bash
touch /opt/arven/data/live/live.stop && sleep 180
cd /opt/arven && unzip -o arven-code.zip && .venv/bin/pip install -e . && chown -R arven:arven /opt/arven
rm data/live/live.stop && systemctl restart arven-live arven-web
```

`data/` и `.env` при этом не затрагиваются. Файлы `config/*.yaml` берутся из архива: если вы меняли их на сервере,
перенесите правки в проект на ноутбуке.
