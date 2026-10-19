from .. import auth
from ..config import Settings
from ..models import SetupGuide, SetupStep, SetupTask
from ..operation import operation

HOME_PAGE = "https://github.com/eukosh/youtube-kit"
PRIVACY_POLICY = "https://github.com/eukosh/youtube-kit/blob/main/PRIVACY.md"
AUDIENCE = "https://console.cloud.google.com/auth/audience"

CLIENT_STEPS = [
    SetupStep(
        title="Create a Google Cloud project",
        tasks=[
            SetupTask(
                do='Name it "YouTube" and click Create. Keep it selected in the top bar for the next steps.',
                url="https://console.cloud.google.com/projectcreate",
            )
        ],
        gcloud="gcloud projects create PROJECT_ID --name=YouTube",  # the ID must be unique across all of Google Cloud
    ),
    SetupStep(
        title="Enable the YouTube APIs",
        tasks=[
            SetupTask(
                do="YouTube Data API v3: click Enable.",
                url="https://console.cloud.google.com/apis/library/youtube.googleapis.com",
            ),
            SetupTask(
                do="YouTube Analytics API: click Enable.",
                url="https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com",
            ),
            SetupTask(
                do="YouTube Reporting API, for thumbnail impressions and click-through rate: click Enable.",
                url="https://console.cloud.google.com/apis/library/youtubereporting.googleapis.com",
            ),
        ],
        gcloud=(
            "gcloud services enable youtube.googleapis.com youtubeanalytics.googleapis.com "
            "youtubereporting.googleapis.com --project=PROJECT_ID"
        ),
    ),
    SetupStep(
        title="Set up the consent screen",
        tasks=[
            SetupTask(
                do='Click "Get started", fill it in, then Create. The emails are only contact info.',
                url="https://console.cloud.google.com/auth/overview",
                values={
                    "App name": "ytk",
                    "User support email": "your email",
                    "Audience": "External (Internal is only for Google Workspace organizations)",
                    "Contact information": "your email",
                },
            )
        ],
    ),
    SetupStep(
        title="Fill in Branding, then publish",
        tasks=[
            SetupTask(
                do="Fill these in and click Save. Leave the logo empty: a logo triggers Google's review.",
                url="https://console.cloud.google.com/auth/branding",
                values={
                    "Application home page": HOME_PAGE,
                    "Application privacy policy link": PRIVACY_POLICY,
                    "Authorized domains": "github.com",
                },
            ),
            SetupTask(
                do='Click "Publish app". Unpublished, only test users can sign in and logins expire in 7 days.',
                url=AUDIENCE,
            ),
        ],
    ),
    SetupStep(
        title="Create the OAuth client",
        tasks=[
            SetupTask(
                do='Click "Create client", fill it in, click Create, then "Download JSON".',
                url="https://console.cloud.google.com/auth/clients",
                values={"Application type": "Desktop app", "Name": "ytk"},
            )
        ],
    ),
]

SIGN_IN_TIPS = [
    SetupTask(
        do='Pick the Google account that owns the channel ("Use another account" if it isn\'t listed), then the channel.'
    ),
    SetupTask(do="Google says it hasn't verified the app. It's your own: click Advanced, then \"Go to ytk (unsafe)\"."),
    SetupTask(do="Allow every permission."),
    SetupTask(
        do='"Access blocked … being tested" means the app isn\'t published yet. Click "Publish app", then sign in again.',
        url=AUDIENCE,
    ),
]

CONNECT = SetupStep(
    title="Connect a channel",
    tasks=[
        SetupTask(
            do="Run `ytk auth login` in a terminal (`uvx --from youtube-kit ytk auth login` if ytk isn't installed). "
            "It finds the downloaded JSON in Downloads, or takes it as `--client-secrets FILE`, then opens Google's "
            "sign-in."
        ),
        *SIGN_IN_TIPS,
    ],
)


@operation(quota=0, read_only=True, idempotent=True, local=True)
def setup_guide(*, project: str | None = None) -> SetupGuide:
    """What is left before the user's channel can be used: a one-time Google Cloud setup, then a Google sign-in.

    The steps happen in the user's browser, so walk them through one step at a time. Once ready, running
    the sign-in again connects another channel.

    Args:
        project: Google Cloud project ID, once known. The links then open with that project selected.
    """
    settings = Settings.from_env()
    channels = auth.my_channels(settings)
    if channels:
        steps = []
    elif settings.client_secrets_file.exists():
        steps = [CONNECT]
    else:
        steps = [*CLIENT_STEPS, CONNECT]
    if project:
        steps = [_in_project(step, project) for step in steps]
    return SetupGuide(ready=bool(channels), channels=channels, steps=steps)


def _in_project(step: SetupStep, project: str) -> SetupStep:
    tasks = [
        task.model_copy(update={"url": f"{task.url}?project={project}"})
        if task.url and "projectcreate" not in task.url
        else task
        for task in step.tasks
    ]
    gcloud = step.gcloud and step.gcloud.replace("PROJECT_ID", project)
    return step.model_copy(update={"tasks": tasks, "gcloud": gcloud})
