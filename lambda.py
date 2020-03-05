import datetime
import json
import os
import uuid

import requests

WORKING_STATUSES = [
    # SUP
    "Open",
    "Investigating",
    "Waiting: Support",

    # Other
    "Review",
    "In QA",
    "In Progress",
    "Reopened",
    "Release",
]

MOBILE_PROJECTS = [
    "WXAP",
    "NEWS",
    "SIE",
    "HAPP"
]

SUPPORT_TD_PROJECT = 2212260595
JIRA_TD_PROJECT = 2215353562
MOBILE_TD_PROJECT = 2230496957
JIRA_DISPLAY_NAME = "Michael Newman"
TODOIST_TOKEN = os.environ.get("TODOIST_TOKEN")


def get_project_id(key):
    project, number = key.split("-")
    if project == "SUP":
        return SUPPORT_TD_PROJECT
    elif project in MOBILE_PROJECTS:
        return MOBILE_TD_PROJECT
    else:
        return JIRA_TD_PROJECT


def get_task_id_from_key(key):
    tasks = requests.get(
        "https://api.todoist.com/rest/v1/tasks",
        params={
            "project_id": get_project_id(key)
        },
        headers={
            "Authorization": f"Bearer {TODOIST_TOKEN}"
        })
    try:
        tasks = tasks.json()
    except json.JSONDecodeError:
        print(tasks.text)
        raise

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
        "project_id": get_project_id(key)
    })
    ret = requests.post(
        "https://api.todoist.com/rest/v1/tasks",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
            "Authorization": f"Bearer {TODOIST_TOKEN}"
        })
    try:
        return ret.json()
    except json.JSONDecodeError:
        print(ret.text)
        raise


def mark_task_done(id):
    return requests.post(f"https://api.todoist.com/rest/v1/tasks/{id}/close",
                         headers={
                             "Authorization": f"Bearer {TODOIST_TOKEN}"
                         })


def mark_task_done_from_key(key):
    task_id = get_task_id_from_key(key)
    if task_id:
        return mark_task_done(task_id)
    print("No Task ID, ignoring")


def update_task(id, change):
    print(f"Updating task, {id}, change: {change}")
    ret = requests.post(
        f"https://api.todoist.com/rest/v1/tasks/{id}",
        data=json.dumps(change),
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
            "Authorization": f"Bearer {TODOIST_TOKEN}"
        })


class ChangeActions(object):
    def __init__(self, jira_key=None, task_id=None, assigned_to_me=None):
        self.jira_key = jira_key
        self.task_id = task_id
        self.assigned_to_me = assigned_to_me
        self.changes = {}
        self.should_mark_done = False

    def mark_task_done(self):
        if self.task_id:
            print(f"Marking task done: {self.task_id}")
            mark_task_done(self.task_id)
        else:
            print(f"Marking task done from key: {self.jira_key}")
            mark_task_done_from_key(self.jira_key)

    def update_task(self, change):
        if self.task_id:
            print(f"Updating Task: {self.task_id}")
            return update_task(self.task_id, change)
        print("No Task ID, ignoring")

    def __getitem__(self, key):
        print(f"Event Change: {key}")
        return getattr(self, f'change_{key}', lambda x: None)

    def change_assignee(self, change):
        if change.get('fromString') == JIRA_DISPLAY_NAME:
            self.should_mark_done = True

    def change_status(self, change):
        if self.assigned_to_me and not change.get('toString') in WORKING_STATUSES:
            self.should_mark_done = True

    def change_resolution(self, change):
        if self.assigned_to_me and change.get('to') is not None:
            self.should_mark_done = True

    def change_priority(self, change):
        update = {'priority': 5 - int(change.get('to'))}
        # If critical or higher, Due Today
        if update['priority'] >= 3:
            update['due_date'] = datetime.date.today().isoformat()
        self.changes.update(update)

    def change_duedate(self, change):
        new_due_date = change.get('to')
        if new_due_date:
            self.changes.update({'due_date': new_due_date})

    def execute(self):
        if self.should_mark_done:
            self.mark_task_done()
        elif self.changes:
            self.update_task(self.changes)


def lambda_handler(event, context):
    task_id = None
    event = json.loads(event['body'])
    key = event['issue']['key']
    print(key)
    print("Full Issue", event['issue'])
    is_support_ticket = key.startswith("SUP")

    # Get all issues that are assigned to me, make sure they have tasks
    assignee = event['issue']['fields'].get('assignee')
    assigneed_to_me = assignee and assignee.get(
        'displayName') == JIRA_DISPLAY_NAME
    if assigneed_to_me and event['issue']['fields']['resolution'] is None and event['issue']['fields']['status']['name'] in WORKING_STATUSES:
        print("Assigned to me and should be active")
        task_id = get_task_id_from_key(key)
        if not task_id:
            print("Creating Task in Todoist")
            task = create_task(event['issue'])
            task_id = task['id']
            print(f"Created task: {task_id}, continuing")
        else:
            print(f"Task found: {task_id}, continuing")

    changes = event.get('changelog', {}).get('items', [])
    if changes:
        print("Changes", changes)
        actions = ChangeActions(key, task_id, assigneed_to_me)
        for change in changes:
            change_field = change.get('field')
            actions[change_field](change)
        actions.execute()

    return {
        'statusCode': 200,
        'body': key
    }
