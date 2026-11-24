from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
import json

from networth import advisor


class Feedback(BaseModel):
  model_config = ConfigDict(extra='forbid')
  feedback: Literal['new', 'useful', 'dismissed', 'incorrect', 'known']
  answer: str = Field(default='', max_length=4000)


def router(store, config, worker):
  api = APIRouter(prefix='/api/advisor')

  def settings_view():
    return dict(values=advisor.settings(store).model_dump(), configured=bool(advisor.api_key(config)),
                timezone=str(advisor.TZ), next_run=store.conn.execute('SELECT next_run FROM advisor_settings WHERE id=1').fetchone()[0],
                accounts=[a.name for a in config.accounts])

  @api.get('')
  async def overview():
    runs = store.conn.execute('SELECT * FROM advisor_runs ORDER BY id DESC LIMIT 30').fetchall()
    latest = store.conn.execute("SELECT * FROM advisor_runs WHERE status='completed' ORDER BY id DESC LIMIT 1").fetchone()
    # Current feedback is overlaid on historical findings when opening a run.
    feedback = {r['topic']:dict(feedback=r['feedback'], answer=r['answer']) for r in store.conn.execute('SELECT topic,feedback,answer FROM advisor_findings')}
    return dict(settings=settings_view(), runs=[advisor.view_run(r) for r in runs],
                latest=advisor.view_run(latest, True) if latest else None, feedback=feedback)

  @api.put('/settings')
  async def save(values: advisor.Settings):
    try:
      advisor.save_settings(store, config, values)
    except ValueError as e:
      raise HTTPException(400, str(e))
    worker.wake.set()
    return settings_view()

  @api.get('/summary')
  async def summary():
    row = store.conn.execute("SELECT report,finished_at FROM advisor_runs WHERE status='completed' ORDER BY id DESC LIMIT 1").fetchone()
    latest = store.conn.execute('SELECT status FROM advisor_runs ORDER BY id DESC LIMIT 1').fetchone()
    feedback = {r['topic']:r['feedback'] for r in store.conn.execute('SELECT topic,feedback FROM advisor_findings')}
    findings = json.loads(row['report'])['findings'] if row else []
    findings = [f for f in findings if feedback.get(f['topic'], 'new') not in ('known','dismissed','incorrect')]
    findings.sort(key=lambda f: ('attention','review','information').index(f['priority']))
    return dict(finished_at=row['finished_at'] if row else None, count=len(findings),
                titles=[f['title'] for f in findings[:2]], status=latest['status'] if latest else None)

  @api.post('/run', status_code=202)
  async def run():
    result = advisor.queue(store)
    worker.wake.set()
    return result

  @api.get('/runs/{run_id}')
  async def history(run_id: int):
    row = store.conn.execute('SELECT * FROM advisor_runs WHERE id=%s', (run_id,)).fetchone()
    if row is None:
      raise HTTPException(404, 'Review not found')
    return advisor.view_run(row, True)

  @api.put('/findings/{topic}/feedback')
  async def feedback(topic: str, values: Feedback):
    with store.conn:
      count = store.conn.execute('UPDATE advisor_findings SET feedback=%s,answer=%s WHERE topic=%s',
                                (values.feedback, values.answer, topic)).rowcount
    if not count:
      raise HTTPException(404, 'Finding not found')
    return values.model_dump()

  return api
