"""Auth plugin using usernames & passwords in the DB, with HTTP basic auth.

Includes API calls for managing users.
"""
from haas import api, model, auth
from haas.rest import rest_call, local
from haas.errors import *
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import relationship
from passlib.hash import sha512_crypt


class User(model.Model):
    """A user of the HaaS.

    A user can be a member of any number of projects, which grants them access
    to that process's resources. A user may also be flagged as an administrator.
    """

    # The user's salted & hashed password. We currently use sha512 as the
    # hashing algorithm:
    hashed_password = Column(String)

    # The projects of which the user is a member.
    projects = relationship('Project', secondary='user_projects', backref='users')

    def __init__(self, label, password):
        """Create a user `label` with the specified (plaintext) password."""
        self.label = label
        self.set_password(password)

    def verify_password(self, password):
        """Return whether `password` is the user's (plaintext) password."""
        return sha512_crypt.verify(password, self.hashed_password)

    def set_password(self, password):
        """Set the user's password to `password` (which must be plaintext)."""
        self.hashed_password = sha512_crypt.encrypt(password)


# A joining table for users and projects, which have a many to many relationship:
user_projects = Table('user_projects', model.Base.metadata,
                      Column('user_id', ForeignKey('user.id')),
                      Column('project_id', ForeignKey('project.id')))


@rest_call('PUT', '/user/<user>')
def user_create(user, password):
    """Create user with given password.

    If the user already exists, a DuplicateError will be raised.
    """

    # XXX: We need to do a bit of refactoring, so this is available outside of
    # haas.api:
    api._assert_absent(User, user)

    user = User(user, password)
    local.db.add(user)
    local.db.commit()


@rest_call('DELETE', '/user/<user>')
def user_delete(user):
    """Delete user.

    If the user does not exist, a NotFoundError will be raised.
    """

    # XXX: We need to do a bit of refactoring, so this is available outside of
    # haas.api:
    user = api._must_find(User, user)

    local.db.delete(user)
    local.db.commit()


@rest_call('POST', '/project/<project>/add_user')
def project_add_user(project, user):
    """Add a user to a project.

    If the project or user does not exist, a NotFoundError will be raised.
    """
    user = api._must_find(User, user)
    project = api._must_find(model.Project, project)
    if project in user.projects:
        raise DuplicateError('User %s is already in project %s'%
                             (user.label, project.label))
    user.projects.append(project)
    local.db.commit()


@rest_call('POST', '/project/<project>/remove_user')
def project_remove_user(project, user):
    """Remove a user from a project.

    If the project or user does not exist, a NotFoundError will be raised.
    """
    user = api._must_find(User, user)
    project = api._must_find(model.Project, project)
    if project not in user.projects:
        raise NotFoundError("User %s is not in project %s"%
                            (user.label, project.label))
    user.projects.remove(project)
    local.db.commit()


class DatabaseAuthBackend(auth.AuthBackend):

    def authenticate(self):
        authorization = rest.local.request.authorization()
        if authorization.password is None:
            rest.local.auth = None
            return

        user = api._must_find(User, authorization.username)
        if user.verify_password(authorization.password):
            rest.local.auth = user
        else:
            # XXX: this is a bit gross; we really ought to just report an
            # authentication failure *now*. instead, this will cause
            # authorization queries to fail later:
            rest.local.auth = None

    def have_admin(self):
        user = rest.local.auth
        return user is not None and user.is_admin

    def have_project_access(self, project):
        user = rest.local.auth
        return user is not None and (user.is_admin or project in user.projects)