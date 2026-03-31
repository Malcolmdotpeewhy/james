def get_account_info():
    account = "acct"
    project = "proj"
    hash = "12345"
    return account, project, hash

account, project, hsh = get_account_info()

issues = []

from dataclasses import dataclass

@dataclass
class IssueDetails:
    title: str
    description: str
    filepath: str
    lineno: int
    confidence: str
    rationale: str
    context: str
    category: str
    impact: str

def add_issue(issue: IssueDetails):
    link = f"https://github.com/{account}/{project}/blob/{hsh}/{issue.filepath}#L{issue.lineno}"
    issues.append({
        "title": issue.title,
        "description": issue.description,
        "deepLink": link,
        "filePath": issue.filepath,
        "lineNumber": issue.lineno,
        "confidence": issue.confidence,
        "rationale": issue.rationale,
        "context": issue.context,
        "category": issue.category,
        "impact": issue.impact
    })
