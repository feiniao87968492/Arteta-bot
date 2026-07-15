from datetime import datetime


def format_sync_status(sqlite_store) -> str:
    latest = sqlite_store.latest_sync_run()
    if not latest:
        return "足球情报同步状态：尚未运行。"
    finished_at = int(latest.get("finished_at") or latest.get("started_at") or 0)
    finished_text = datetime.fromtimestamp(finished_at).strftime("%Y-%m-%d %H:%M:%S") if finished_at else "未知"
    lines = [
        "足球情报同步状态",
        "最后成功时间：%s" % finished_text,
        "最后任务类型：%s" % (latest.get("job_type") or "unknown"),
        "任务状态：%s" % (latest.get("status") or "unknown"),
        "搜索主题数：%s" % int(latest.get("query_count") or 0),
        "抓取候选数：%s" % int(latest.get("fetched_count") or 0),
        "新增/更新：%s" % (int(latest.get("inserted_count") or 0) + int(latest.get("updated_count") or 0)),
        "重复：%s" % int(latest.get("duplicate_count") or 0),
        "失败来源数：%s" % int(latest.get("failed_source_count") or 0),
        "待索引：%s" % sqlite_store.count_items_by_index_status("pending"),
        "索引失败：%s" % sqlite_store.count_items_by_index_status("failed"),
        "当前数据库记录数：%s" % sqlite_store.count_news_items(),
    ]
    if latest.get("error_summary"):
        lines.append("错误摘要：%s" % latest.get("error_summary"))
    return "\n".join(lines)


def register_scheduled_jobs(scheduler, orchestrator_factory, settings):
    if not getattr(settings, "enabled", False):
        return []
    jobs = []

    def add_job(job_id, cron_text, job_type):
        fields = str(cron_text or "").split()
        if len(fields) != 5:
            return
        minute, hour, day, month, day_of_week = fields

        @scheduler.scheduled_job(
            "cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            id=job_id,
            misfire_grace_time=300,
        )
        async def _job():
            orchestrator = orchestrator_factory()
            await orchestrator.run_sync(job_type)

        jobs.append(job_id)

    add_job("football_intelligence_deep", getattr(settings, "deep_sync_cron", ""), "deep")
    add_job("football_intelligence_incremental", getattr(settings, "incremental_sync_cron", ""), "incremental")
    return jobs
