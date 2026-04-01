import os

from services.queue import get_redis_url


def main():
    redis_url = get_redis_url()
    if not redis_url:
        raise SystemExit("REDIS_URL não configurado. Defina no .env para rodar o worker.")
    try:
        from redis import Redis  # type: ignore
        from rq import Connection, Worker  # type: ignore
    except Exception as e:
        raise SystemExit(f"Dependências do worker ausentes (rq/redis): {e}")

    conn = Redis.from_url(redis_url)
    queues = [os.getenv("RQ_QUEUES", "default")]
    with Connection(conn):
        w = Worker(queues)
        w.work(with_scheduler=False)


if __name__ == "__main__":
    main()

