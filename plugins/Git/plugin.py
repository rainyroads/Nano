import os
import logging
from git import Repo


class GitManager:
    """
    Git plugin for development
    """
    def __init__(self):
        """
        Initialize a new Git Manager instance
        """
        self.log = logging.getLogger('nano.plugins.git')
        # Set our repo and origin branch
        self.repo = Repo(os.getcwd())
        self.origin = self.repo.remotes['origin']

    def pull(self):
        """
        Pull our latest commit and return some basic fetch information on the master branch
        """
        self.log.info('Pulling the most recent commit')
        fetch_info = self.origin.pull().pop(0)
        return fetch_info.name, fetch_info.commit, fetch_info.old_commit

    def current(self):
        """
        Fetch the current commit
        """
        self.log.info('Fetching the current commit')
        return self.origin.refs.master.commit

    @staticmethod
    def commit_bar(commit, max_length=16, color=True):
        """
        Formats and returns an insertion / deletions bar for a given commit

        Args:
            commit(git.Commit): The Git Commit instance
            max_length(int, optional): The maximum length of the commit bar. Defaults to 16
            color(bool): Apply HTML color formatting to the pluses and minuses

        Returns:
            str
        """
        insertions = int(commit['insertions'])
        deletions = int(commit['deletions'])
        total = insertions + deletions

        # Bar formatting
        def bar(inserts, deletes):
            # Set the pluses and minuses
            pluses  = '+' * inserts
            minuses = '-' * deletes

            # HTML color formatted response
            if color:
                bar_string = '<p class="fg-green">{pluses}</p><p class="fg-red">{minuses}</p>'
                return bar_string.format(pluses=pluses, minuses=minuses)

            # Unformatted response
            return pluses + minuses

        # If our total is less than our limit, we don't need to do anything further
        if total <= max_length:
            return bar(insertions, deletions)

        # Otherwise, trim the insertions / deletions to adhere to the max length
        percent_insertions = insertions / total
        insertions = round(total * percent_insertions)
        deletions = total - insertions

        return bar(insertions, deletions)