import json
import os
from .cog_base import CogBase
from ..bot import Ranger
import discord
from discord.commands import message_command
from loguru import logger
import requests

GRAPHQL_URL = "https://api.github.com/graphql"
GRAPHQL_HEADERS = {"Authorization": f"token {os.getenv('GH_PAT')}"}
PROJECT_ID = "PVT_kwDOBiHIjc4AFHLv"
REPO_ID = "R_kgDOGqDXuw"


def graph_ql_request(query: str) -> dict:
    """Makes request to GH api"""
    return requests.post(
        GRAPHQL_URL, data=json.dumps({"query": query}), headers=GRAPHQL_HEADERS
    ).json()


def get_repo_labels() -> dict:
    """Gets all labels for repo"""
    query = """
    { 
        repository(name: "bfportal.gg", owner: "battlefield-portal-community"){
            id,
            labels(first: 100){
                totalCount,
                edges{
                    node{
                        id,
                        name,
                        description,
                    }
                }
            }
        }
    }    
    """
    return graph_ql_request(query)


def add_issue_to_repo(
    title: str, description: str = "", label_ids: list = None
) -> dict:
    """Adds a new issue to the repo"""
    if not label_ids:
        label_ids = []

    #  resp {'data': {'createIssue': {'issue': {'title': 'testing again 🥲', 'id': 'I_kwDOGqDXu85VITP9'}}}}

    mutation = """
mutation {{
    createIssue (input: {{
        title: "{title}", 
        body: "{body}", 
        repositoryId: "{repo_id}",
        labelIds: {label_ids}
    }}){{
        issue {{
            title,
            body,
            id
        }}
    }}
}}
    """.strip().format(
        title=title,
        body=description,
        repo_id=REPO_ID,
        project_id=PROJECT_ID,
        label_ids=label_ids,
    )
    logger.debug(mutation)
    return graph_ql_request(mutation)


def add_issue_to_project(issue_id: str):
    """adds a issue to a project"""
    mutation = """
mutation {{
    addProjectV2ItemById(input: {{projectId: "PVT_kwDOBiHIjc4AFHLv" contentId: "{issue_id}"}}) {{
        item {{
            id
        }}
    }}
}}
    """.strip().format(
        issue_id=issue_id
    )
    return graph_ql_request(mutation)


def add_label_to_issue(issue_id: str, label_ids: list) -> dict:
    """adds labels to a issue"""
    mutation = (
        """
mutation {{
    addLabelsToLabelable(input: {{labelableId: "{issue_id}",labelIds: {label_ids} }}){{
        labelable{{
            labels{{
                totalCount
            }}
        }}
    }}
}}""".strip()
        .format(issue_id=issue_id, label_ids=[f"{label_id}" for label_id in label_ids])
        .replace("'", '"')
    )
    return graph_ql_request(mutation)


class Dropdown(discord.ui.Select):
    def __init__(
        self,
        root_msg: discord.Message,
        issue_id: str,
        issue_title: str,
        labels: dict,
        description: str = None,
    ):

        self.issue_id = issue_id
        self.issue_title = issue_title
        self.description = description
        self.root_msg = root_msg
        options = [
            discord.SelectOption(
                label="None", description="Skip adding label", value="none", emoji="💠"
            )
        ]
        for labelID, labelItem in labels.items():
            options.append(
                discord.SelectOption(
                    label=labelItem["name"],
                    description=labelItem["description"],
                    value=labelID,
                )
            )
        super().__init__(
            placeholder="Add labels to this issue",
            min_values=1,
            max_values=5,
            options=options[0:25],
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            if "none" not in self.values:
                resp = add_label_to_issue(self.issue_id, label_ids=self.values)
                if not resp.get("errors", False):
                    if not add_issue_to_project(self.issue_id).get("errors", False):
                        logger.debug("In successful")
                        await interaction.response.send_message(
                            embeds=[
                                discord.Embed(
                                    title="New Issue Open",
                                    description=f"`Title` **{self.issue_title}**\n{f'`Description` {self.description[0:200]}' if self.description else ''}\n Added to todo :- ✅",
                                    colour=discord.Colour.green(),
                                )
                            ]
                        )
                    else:
                        await interaction.response.send_message(
                            embeds=[
                                discord.Embed(
                                    title="New Issue Open",
                                    description=f"`Title` **{self.issue_title}**\n{f'`Description` {self.description[0:200]}' if self.description else ''}\n Added to todo :- ❌",
                                    colour=discord.Colour.dark_green(),
                                )
                            ]
                        )
                else:
                    await interaction.response.send_message(
                        embeds=[
                            discord.Embed(
                                title="Failed to create issue",
                                colour=discord.Colour.red(),
                            )
                        ]
                    )
        except (requests.HTTPError, requests.Timeout):
            await interaction.response.send_message(
                embeds=[
                    discord.Embed(
                        title="Failed to create issue",
                        colour=discord.Colour.red(),
                    )
                ]
            )


class IssueModal(discord.ui.Modal):
    def __init__(
        self,
        bot_: Ranger,
        issue_title: str,
        root_msg: discord.Message,
        labels: dict = None,
        *args,
        **kwargs,
    ):
        c_args = [
            discord.ui.InputText(
                label="Issue Title", placeholder="Enter Issue Title", value=issue_title
            ),
            discord.ui.InputText(
                label="Description",
                placeholder="Enter Description of issue",
                style=discord.InputTextStyle.long,
                required=False,
            ),
        ]
        super().__init__(
            *c_args,
            *args,
            title="Add New Issue",
            **kwargs,
        )
        self.bot = bot_
        self.labels = labels
        self.root_msg = root_msg

    async def callback(self, interaction: discord.Interaction):
        title = self.children[0].value
        body = self.children[1].value
        final_body = (
            body
            + """\n\n<sup>Issue create by [ranger](https://github.com/battlefield-portal-community/ranger), click [here]({jump_url}) to jump to message in [discord server](https://bfportal.gg/join)</sup>""".format(  # noqa
                jump_url=self.root_msg.jump_url
            )
        )
        resp = add_issue_to_repo(title=title, description=final_body)
        if not resp.get("errors", False):
            issue = resp["data"]["createIssue"]["issue"]
            view = discord.ui.View()
            view.add_item(
                Dropdown(
                    interaction.message,
                    issue["id"],
                    issue["title"],
                    self.labels,
                    description=body,
                )
            )
            await interaction.response.send_message(
                embeds=[discord.Embed(title="Add Label to issue")],
                view=view,
                ephemeral=True,
                delete_after=60,
            )


class TODOAdder(CogBase):
    def __init__(self, bot: Ranger):
        self.bot = bot
        labels_resp = get_repo_labels()
        self.labels = dict()
        if not labels_resp.get("errors", False):
            logger.debug(
                f'Got {labels_resp["data"]["repository"]["labels"]["totalCount"]} labels'
            )
            for node_item in labels_resp["data"]["repository"]["labels"]["edges"]:
                node = node_item["node"]
                self.labels[node["id"]] = {
                    "name": node["name"],
                    "description": node["description"],
                }

    @message_command(name="Open New Issue")
    async def todo_message_command(
        self, ctx: discord.ApplicationContext, message: discord.Message
    ):
        await ctx.send_modal(
            IssueModal(
                self.bot, message.content[0:4000], root_msg=message, labels=self.labels
            )
        )


def setup(bot: Ranger):
    bot.add_cog(TODOAdder(bot))


if __name__ == "__main__":
    add_issue_to_repo(
        title="Test",
        description="So?",
    )
