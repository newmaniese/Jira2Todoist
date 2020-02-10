import datetime
import json
import os
import uuid

import requests

WORKING_STATUSES = [
    "Open",
    "Investigating",
    "Waiting: Support"
]


SUPPORT_TD_PROJECT = 2212260595
JIRA_TD_PROJECT = 2215353562
JIRA_USERNAME = "mnewman"
TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")


def get_task_id_from_key(key):
    tasks = requests.get(
        "https://api.todoist.com/rest/v1/tasks",
        params={
            "project_id": key.startswith("SUP") and SUPPORT_TD_PROJECT or JIRA_TD_PROJECT
        },
        headers={
            "Authorization": f"Bearer {TODOIST_TOKEN}"
        })
    tasks = tasks.json()
    for task in tasks:
        if key in task['content']:
            return task['id']

def create_task(issue):
    due_date = issue['fields']['duedate']
    key = issue['key']
    summary = issue['fields']['summary']
    priority = 5 - int(issue['fields']['priority']['id'])
    # If critical or higher, Due Today
    if priority >= 3:
        due_date = datetime.date.today().isoformat()
    data = json.dumps({
        "content": f"[{key}: {summary}](https://grahamdigital.atlassian.net/browse/{key})",
        "due_date": due_date,
        "priority": 5 - int(issue['fields']['priority']['id']),
        "project_id": key.startswith("SUP") and SUPPORT_TD_PROJECT or JIRA_TD_PROJECT
    })
    ret = requests.post(
        "https://api.todoist.com/rest/v1/tasks",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
            "Authorization": f"Bearer {TODOIST_TOKEN}"
        })
    return ret.json()

def mark_task_done(id):
    return requests.post(f"https://api.todoist.com/rest/v1/tasks/{id}/close",
            headers={
                "Authorization": f"Bearer {TODOIST_TOKEN}"
            })

def mark_task_done_from_key(key):
    task_id = get_task_id_from_key(key)
    if task_id:
        return mark_task_done(task_id)

def update_task(id, change):
    return requests.post(
        f"https://api.todoist.com/rest/v1/tasks/{id}",
        data=json.dumps(change),
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
            "Authorization": f"Bearer {TODOIST_TOKEN}"
        }).json()

class ChangeActions(object):
    def __init__(self, jira_key=None, task_id=None):
        self.jira_key = jira_key
        self.task_id = task_id

    def mark_task_done(self):
        if self.task_id:
            mark_task_done(self.task_id)
        else:
            mark_task_done_from_key(self.jira_key)

    def update_task(self, change):
        if self.task_id:
            update_task(self.task_id, change)

    def __getitem__(self, key):
        return getattr(self, f'change_{key}', lambda x: None)

    def change_assignee(self, change):
        if change.get('from') == JIRA_USERNAME:
            self.mark_task_done()

    def change_status(self, change):
        if not change.get('toString') in WORKING_STATUSES:
            self.mark_task_done()

    def change_resolution(self, change):
        if change.get('to') is not None:
            self.mark_task_done()

    def change_priority(self, change):
        update = { 'priority' : 5 - int(change.get('to')) }
        # If critical or higher, Due Today
        if update['priority'] >= 3:
            update['due_date'] = datetime.today().isoformat()
        self.update_task(update)

    def change_duedate(self, change):
        self.update_task({ 'due_date': change.get('to') })


def lambda_handler(event, context):
    task_id = None
    event = json.loads(event['body'])
    print(event['issue'])
    key = event['issue']['key']
    print(key)
    is_support_ticket = key.startswith("SUP")

    # Get all issues that are assigned to me, make sure they have tasks
    assignee = event['issue']['fields'].get('assignee')
    if assignee and assignee.get('name') == JIRA_USERNAME and \
            event['issue']['fields']['resolution'] is None and \
            (is_support_ticket and event['issue']['fields']['status']['name'] in WORKING_STATUSES or not is_support_ticket):
        print("Assigned to me")
        task_id = get_task_id_from_key(key)
        if not task_id:
            task = create_task(event['issue'])
            task_id = task['id']

    changes = event.get('changelog', {}).get('items', [])
    if changes:
        actions = ChangeActions(key, task_id)
        for change in changes:
            change_field = change.get('field')
            actions[change_field](change)

    return {
        'statusCode': 200,
        'body': key
    }
