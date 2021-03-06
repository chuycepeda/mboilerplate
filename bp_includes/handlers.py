# -*- coding: utf-8 -*-
"""
    A real simple app for using webapp2 with auth and session.

    It just covers the basics. Creating a user, login, logout
    and a decorator for protecting certain handlers.

    Routes are setup in routes.py and added in main.py
"""
# python imports
import logging
import json
import requests
from datetime import date, timedelta
import time

# appengine imports
import os, webapp2, MySQLdb
from webapp2_extras import security
from webapp2_extras.auth import InvalidAuthIdError, InvalidPasswordError
from webapp2_extras.i18n import gettext as _
from webapp2_extras.appengine.auth.models import Unique
from google.appengine.ext import ndb, blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.api import taskqueue, users, images
from google.appengine.api.datastore_errors import BadValueError
from google.appengine.runtime import apiproxy_errors
from google.appengine.ext.webapp import mail_handlers
from google.appengine.api import channel

# local imports
import models, messages, forms
from lib import utils, captcha, bitly
from lib.cartodb import CartoDBAPIKey, CartoDBException
from lib.basehandler import BaseHandler
from lib.decorators import user_required, taskqueue_method, user_admin_role_required, user_coord_role_required, user_member_role_required

# global variables
CLOUDSQL_CONNECTION_NAME = os.environ.get('CLOUDSQL_CONNECTION_NAME')
CLOUDSQL_DB = os.environ.get('CLOUDSQL_DB')
CLOUDSQL_USER = os.environ.get('CLOUDSQL_USER')
CLOUDSQL_PASSWORD = os.environ.get('CLOUDSQL_PASSWORD')

""" --------------- HELPERS --------------- """

def captchaBase(self):
    if self.app.config.get('captcha_public_key') == "" or \
                    self.app.config.get('captcha_private_key') == "":
        chtml = '<div class="alert alert-danger"><strong>Error</strong>: You have to ' \
                '<a href="http://www.google.com/recaptcha/" target="_blank">sign up ' \
                'for API keys</a> in order to use reCAPTCHA.</div>' \
                '<input type="hidden" name="recaptcha_challenge_field" value="manual_challenge" />' \
                '<input type="hidden" name="recaptcha_response_field" value="manual_challenge" />'
    else:
        chtml = captcha.displayhtml(public_key=self.app.config.get('captcha_public_key'))
    return chtml

def disclaim(_self, **kwargs):
    """
        This method is used as a validator previous to loading a get handler for most of user's screens.
        It can either redirect user to login, edit cfe data and edit home data, or
        return required params, user_info and user_home values.
    """
    _params = {}
    user_info = _self.user_model.get_by_id(long(_self.user_id))        
    
    #0: FOR PERSONALIZATION MEANS WE TAKE CARE OF BEST DATA TO ADDRESS USER
    _params['email'] = user_info.email
    _params['last_name'] = user_info.last_name
    _params['last_name_i'] = user_info.last_name[0] + "." if len(user_info.last_name) >= 1 else ""
    _params['name'] = user_info.name
    _params['name_i'] = user_info.name[0].upper()
    _params['role'] = user_info.get_role
    _params['phone'] = user_info.phone if user_info.phone != None else ""
    _params['gender'] = user_info.gender if user_info.gender != None else ""
    _params['birth'] = user_info.birth.strftime("%Y-%m-%d") if user_info.birth != None else ""
    _params['has_picture'] = True if user_info.image_url != -1 else False
    _params['has_address'] = True if user_info.address is not None else False
    _params['address_from'] = False
    if _params['has_address']:
        if user_info.address.address_from_coord is not None:
            lat = str(user_info.address.address_from_coord.lat)
            lng = str(user_info.address.address_from_coord.lon)
            _params['address_from_coord'] = lat + "," + lng
        _params['address_from'] = user_info.address.address_from
    if not _params['has_picture']:
        _params['disclaim'] = True
    else:
        _params['user_picture_url'] = user_info.image_url
    if _self.app.config.get('has_referrals'):
        _params['link_referral'] = user_info.link_referral
    _params['date'] = date.today().strftime("%Y-%m-%d")
    return _params, user_info

def connect_to_cloudsql():
    # When deployed to App Engine, the `SERVER_SOFTWARE` environment variable
    # will be set to 'Google App Engine/version'.
    if os.getenv('SERVER_SOFTWARE', '').startswith('Google App Engine/'):
        # Connect using the unix socket located at
        # /cloudsql/cloudsql-connection-name.
        cloudsql_unix_socket = os.path.join(
            '/cloudsql', CLOUDSQL_CONNECTION_NAME)

        db = MySQLdb.connect(
            unix_socket=cloudsql_unix_socket,
            user=CLOUDSQL_USER,
            passwd=CLOUDSQL_PASSWORD,
            db=CLOUDSQL_DB)

    # If the unix socket is unavailable, then try to connect using TCP. This
    # will work if you're running a local MySQL server or using the Cloud SQL
    # proxy, for example:
    #
    #   $ cloud_sql_proxy -instances=your-connection-name=tcp:3306
    #
    else:
        db = MySQLdb.connect(
            host='127.0.0.1', user=CLOUDSQL_USER, passwd=CLOUDSQL_PASSWORD)

    return db
       
class RestBasicHelper(BaseHandler):
    @user_required
    def get(self):
        r = {}
        r['rows'] = []
        r['total_rows'] = 0
        r['error'] = 'none'
        r['status'] = '200'

        try:
            #do the rows and total rows loading according to GET helper use cases
            logging.info("Success retrieving data: %s" % r['rows'])
        except Exception, e:
            logging.error("Error retrieving data: %s" % e)
            r['error'] = "Error retrieving data: %s" % e
            r['status'] = '500'

        self.send_json(r)

    @user_required
    def post(self):
        
        d = {}
        d['rows'] = []
        d['error'] = 'none'
        d['status'] = '200'
        
        try:
            #do the rows and total rows loading according to POST helper use cases
            logging.info("Success saving data: %s" % r['rows'])
        except Exception, e:
            logging.error("Error saving data: %s" % e)
            d['rows'] = []
            d['error'] = "Error saving data: %s" % e
            d['status'] = '500'
            pass

        d['total_rows'] = len(d['rows']) 
        self.send_json(d)

class RestMySQLHelper(BaseHandler):
    # https://cloud.google.com/sql/docs/mysql/quickstart shows how to create tables directly at cloud console

    @user_admin_role_required
    def get(self):
        """Simple request handler that shows all of the MySQL variables."""
        # Example query invariant for strings or numbers
        # with protection against SQL injections
        #   cursor.execute("""SELECT name, phone_number 
        #                       FROM coworkers 
        #                       WHERE name=%s 
        #                       AND clue > %s 
        #                       LIMIT 5""",
        #                   (name, clue_threshold)) #important hint: if there's only one element in query params, a comma must be included as if second value is null
        self.response.headers['Content-Type'] = 'application/json'

        # ensure there's no command to modify our database
        q = self.request.get('q') if (self.request.get('q') and 'insert' not in self.request.get('q').lower() and 'update' not in self.request.get('q').lower() and 'delete' not in self.request.get('q').lower() and 'create' not in self.request.get('q').lower() and 'alter' not in self.request.get('q').lower() and 'rename' not in self.request.get('q').lower() and 'drop' not in self.request.get('q').lower()) else 'SHOW VARIABLES'        
        
        d = {}
        d['rows'] = []
        d['error'] = 'none'
        d['status'] = '200'

        try:
            db = connect_to_cloudsql()
            cursor = db.cursor()

            # add here if-else statements according to GET helper use cases
            cursor.execute(q)

            for r in cursor.fetchall():
                d['rows'].append(r)

            cursor.close()
            db.close()

        except MySQLdb.Error, e:
            try:
                d['error'] = "MySQL Error [%d]: %s" % (e.args[0], e.args[1])
                #d['error-ref'] = 'https://dev.mysql.com/doc/refman/5.6/en/error-messages-server.html'
            except IndexError:
                d['error'] = "MySQL Error: %s" % str(e)
            d['rows'] = []
            d['status'] = '500'
            pass                

        d['total_rows'] = len(d['rows'])
        self.send_json(d)

    @user_admin_role_required
    def post(self):
        kind = self.request.get('kind') if self.request.get('kind') != '' else None
        
        d = {}
        d['rows'] = []
        d['error'] = 'none'
        d['status'] = '200'

        try:
            db = connect_to_cloudsql()
            cursor = db.cursor()

            # cursor.execute("SELECT * FROM TABLE WHERE PARAM_A = %s AND PARAM_B = %s", 
            #                     (VALUE_A, VALUE_B))
            # d['msg'] = "item already exists in TABLE: PARAM_A '%s' PARAM_B '%s'" % (VALUE_A, VALUE_B)
            # # if there's no exact pair, try to update with PARAM_B as key
            # if cursor.rowcount == 0:
            #     cursor.execute("UPDATE TABLE SET PARAM_A = %s WHERE PARAM_B = %s", 
            #             (VALUE_A, VALUE_B))
            #     d['msg'] = "updated row in TABLE: PARAM_A '%s' PARAM_B '%s'" % (VALUE_A, VALUE_B)
            #     # if there's no exact PARAM_B, try to insert
            #     if cursor.rowcount == 0:
            #         cursor.execute("INSERT INTO TABLE (PARAM_A, PARAM_B) VALUES (%s, %s)", 
            #                         (ocr_text_match, VALUE_B))
            
            # for r in cursor.fetchall():
            #     d['rows'].append(r)
            
            logging.info(d['msg'])
            # Make sure data is committed to the database
            db.commit()
            cursor.close()
            db.close()

        except MySQLdb.Error, e:
            try:
                d['error'] = "MySQL Error [%d]: %s" % (e.args[0], e.args[1])
                d['msg'] = d['error']
            except IndexError:
                d['error'] = "MySQL Error: %s" % str(e)
                d['msg'] = d['error']
            
            logging.info(d['msg'])
            d['rows'] = []
            d['status'] = '500'

            if db:
                db.rollback()
            pass
        
        d['total_rows'] = len(d['rows']) # also available at cursor.rowcount
        self.send_json(d)

""" --------------- MESSAGING + TASKQUEUES HANDLERS --------------- """
#inbound service: mail bounce
class LogBounceHandler(mail_handlers.BounceNotificationHandler):
    def receive(self, bounce_message):
        logging.info('Received bounce post ... [%s]', self.request)
        logging.info('Bounce original: %s', bounce_message.original)
        logging.info('Bounce notification: %s', bounce_message.notification)
#inbound service: mail
class LogReceivedEmailHandler(mail_handlers.InboundMailHandler):
    def receive(self, mail_message):
        try:
            import re
            email_pattern = re.compile(r'([\w\-\.]+@(\w[\w\-]+\.)+[\w\-]+)')
            match = email_pattern.findall(mail_message.sender)
            email_addr = match[0][0] if match else ''
            title = mail_message.subject
            content = ''
            for content_t, body in mail_message.bodies('text/plain'):
                content += body.decode()
            attachments = getattr(mail_message, 'attachments', None)

            logging.info('Received email post...')
            logging.info('From: %s' % email_addr)
            logging.info('Subject: %s' % title)
            logging.info('Content: %s' % content)
            logging.info('Attachments: %s' % attachments)

            if email_addr != '':
                user = models.User.get_by_email(email_addr)
                if user:
                    channel.send_message(get_notification_client_id(user.key.id()), json.dumps(messages.incoming_email_notification))

        except Exception, e:
            logging.info('Received email post but something went wrong: %s' % e)
        
class SendEmailHandler(BaseHandler):
    """
    Core Handler for sending Emails
    Use with TaskQueue
    """

    @taskqueue_method
    def post(self):

        from google.appengine.api import mail, app_identity
        from lib import sendgrid
        from lib.sendgrid import SendGridError, SendGridClientError, SendGridServerError 

        to = self.request.get("to")
        subject = self.request.get("subject")
        body = self.request.get("body")
        sender = self.request.get("sender")

        if sender != '' or not utils.is_email_valid(sender):
            if utils.is_email_valid(self.app.config.get('contact_sender')):
                sender = self.app.config.get('contact_sender')
            else:
                app_id = app_identity.get_application_id()
                sender = "%s Mail <no-reply@%s.appspotmail.com>" % (self.brand['app_name'],app_id)

        if self.app.config['log_email']:
            try:
                logEmail = models.LogEmail(
                    sender=sender,
                    to=to,
                    subject=subject,
                    body=body,
                    when=utils.get_date_time("datetimeProperty")
                )
                logEmail.put()
            except (apiproxy_errors.OverQuotaError, BadValueError):
                logging.error("Error saving Email Log in datastore")



        if self.app.config.get('sendgrid_priority'):
            # using sendgrid
            try:
                sg = sendgrid.SendGridClient(self.app.config.get('sendgrid_login'), self.app.config.get('sendgrid_passkey'))
                logging.info("sending with sendgrid client: %s" % sg)
                message = sendgrid.Mail()
                message.add_to(to.split(','))
                message.set_subject(subject)
                message.set_html(body)
                message.set_text(body)
                message.set_from(sender)
                status, msg = sg.send(message)
            except Exception, e:
                logging.error("Error sending email: %s" % e)
        else:
            #using appengine email 
            try:            
                message = mail.EmailMessage()
                message.sender = sender
                message.to = to
                message.subject = subject
                message.html = body
                message.send()
                logging.info("... sending email to: %s ..." % to)
            except Exception, e:
                logging.error("Error sending email: %s" % e)       

class ResendActivationEmailHandler(BaseHandler):
    """
    Handler to resend activation email
    """

    def get(self, user_id, token):
        try:
            if not self.user_model.validate_resend_token(user_id, token):
                message = _(messages.used_activation_link)
                self.add_message(message, 'danger')
                return self.redirect_to('login')

            user = self.user_model.get_by_id(long(user_id))
            email = user.email

            if (user.activated == False):
                # send email
                subject = _(messages.email_activation_subject)
                confirmation_url = self.uri_for("account-activation",
                                                user_id=user.get_id(),
                                                token=self.user_model.create_auth_token(user.get_id()),
                                                _full=True)
                # load email's template
                template_val = {
                    "app_name": self.brand['app_name'],
                    "username": user.name,
                    "confirmation_url": confirmation_url,
                    "brand_email_logo": self.brand['brand_email_logo'],
                    "brand_color": self.brand['brand_color'],
                    "brand_secondary_color": self.brand['brand_secondary_color'],
                    "support_url": self.uri_for("contact", _full=True),
                    "twitter_url": self.app.config.get('twitter_url'),
                    "facebook_url": self.app.config.get('facebook_url'),
                    "faq_url": self.uri_for("faq", _full=True)
                }
                body_path = "%s/emails/account_activation.txt" % self.app.config.get('app_lang')
                body = self.jinja2.render_template(body_path, **template_val)

                email_url = self.uri_for('taskqueue-send-email')
                taskqueue.add(url=email_url, params={
                    'to': str(email),
                    'subject': subject,
                    'body': body,
                })

                self.user_model.delete_resend_token(user_id, token)

                message = _(messages.resend_success).format(email)
                self.add_message(message, 'success')
                return self.redirect_to('login')
            else:
                message = _(messages.activation_success)
                self.add_message(message, 'warning')
                return self.redirect_to('materialize-home')

        except (KeyError, AttributeError), e:
            logging.error("Error resending activation email: %s" % e)
            message = _(messages.post_error)
            self.add_message(message, 'danger')
            return self.redirect_to('login')

#inbound service: channel presence
def get_notification_client_id(user):
    return 'notify-' + str(user)
class GetChannelToken(BaseHandler):

    @user_required
    def get(self):
        client_id = get_notification_client_id(self.user_id)
        token = channel.create_channel(client_id, 60) # default channel expiration is set to 60 minutes
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps({'token': token}))
        # once the channel is open we can send a message using (see example with LogReceivedEmailHandler):
        #channel.send_message(get_notification_client_id(user), json.dumps("Hello darkness my old friend."))
class ClientConnectedHandler(BaseHandler):
    def post(self):
        logging.info('{} has connected a channel'.format(self.request.get('from')))
class ClientDisconnectedHandler(BaseHandler):
    def post(self):
        logging.info('{} has disconnected a channel'.format(self.request.get('from')))

""" --------------- ACCOUNT HANDLERS --------------- """

#LOGIN

class LoginRequiredHandler(BaseHandler):
    def get(self):
        continue_url = self.request.get_all('continue')
        self.redirect(users.create_login_url(dest_url=continue_url))

class PasswordResetHandler(BaseHandler):
    """
    Password Reset Handler with Captcha
    """

    def get(self):
        if self.user:
            self.auth.unset_session()
        params = {
            'captchahtml': captchaBase(self),
        }
        return self.render_template('%s/materialize/landing/password_reset.html' % self.app.config.get('app_lang'), **params)

    def post(self):
        # check captcha
        response = self.request.POST.get('g-recaptcha-response')
        remote_ip = self.request.remote_addr

        cResponse = captcha.submit(
            response,
            self.app.config.get('captcha_private_key'),
            remote_ip)

        if cResponse.is_valid:
            # captcha was valid... carry on..nothing to see here
            pass
        else:
            _message = _(messages.captcha_error)
            self.add_message(_message, 'danger')
            return self.redirect_to('password-reset')

        #check if we got an email or username
        email_or_username = str(self.request.POST.get('email_or_username')).lower().strip()
        if utils.is_email_valid(email_or_username):
            user = self.user_model.get_by_email(email_or_username)
        else:
            auth_id = "own:%s" % email_or_username
            user = self.user_model.get_by_auth_id(auth_id)

        if user is not None:
            user_id = user.get_id()
            token = self.user_model.create_auth_token(user_id)
            email_url = self.uri_for('taskqueue-send-email')
            reset_url = self.uri_for('password-reset-check', user_id=user_id, token=token, _full=True)
            subject = _(messages.email_passwordassist_subject)

            # load email's template
            template_val = {
                "username": user.name,
                "email": user.email,
                "reset_password_url": reset_url,
                "brand_email_logo": self.brand['brand_email_logo'],
                "brand_color": self.brand['brand_color'],
                "brand_secondary_color": self.brand['brand_secondary_color'],
                "support_url": self.uri_for("contact", _full=True),
                "twitter_url": self.app.config.get('twitter_url'),
                "facebook_url": self.app.config.get('facebook_url'),
                "faq_url": self.uri_for("faq", _full=True),
                "app_name": self.brand['app_name'],
            }

            body_path = "%s/emails/reset_password.txt" % self.app.config.get('app_lang')
            body = self.jinja2.render_template(body_path, **template_val)
            taskqueue.add(url=email_url, params={
                'to': user.email,
                'subject': subject,
                'body': body,
                'sender': self.app.config.get('contact_sender'),
            })
            _message = _(messages.password_reset)
            self.add_message(_message, 'success')
        else:
            _message = _(messages.password_reset_invalid_email)
            self.add_message(_message, 'warning')

        return self.redirect_to('login')

class PasswordResetCompleteHandler(BaseHandler):
    """
    Handler to process the link of reset password that received the user
    """

    def get(self, user_id, token):
        verify = self.user_model.get_by_auth_token(int(user_id), token)
        params = {}
        if verify[0] is None:
            message = _(messages.password_reset_invalid_link)
            self.add_message(message, 'warning')
            return self.redirect_to('password-reset')

        else:
            user = self.user_model.get_by_id(long(user_id))
            params = {
                '_username':user.name
            }
            return self.render_template('%s/materialize/landing/password_reset_complete.html' % self.app.config.get('app_lang'), **params)

    def post(self, user_id, token):
        verify = self.user_model.get_by_auth_token(int(user_id), token)
        user = verify[0]
        password = self.form.password.data.strip()
        if user and self.form.validate():
            # Password to SHA512
            password = utils.hashing(password, self.app.config.get('salt'))

            user.password = security.generate_password_hash(password, length=12)
            user.put()
            # Delete token
            self.user_model.delete_auth_token(int(user_id), token)
            # Login User
            self.auth.get_user_by_password(user.auth_ids[0], password)
            self.add_message(_(messages.passwordchange_success), 'success')
            return self.redirect_to('materialize-home')

        else:
            self.add_message(_(messages.passwords_mismatch), 'danger')
            return self.redirect_to('password-reset-check', user_id=user_id, token=token)

    @webapp2.cached_property
    def form(self):
        return forms.PasswordResetCompleteForm(self)

class MaterializeLoginRequestHandler(BaseHandler):
    """
    Handler for authentication
    """

    def get(self):
        """ Returns a simple HTML form for login """

        if self.user:
            if self.app.config.get('simplify'):
                return self.redirect_to('materialize-home')
            return self.redirect_to('landing')

        params = {
            'captchahtml': captchaBase(self),
        }
        continue_url = self.request.get('continue').encode('ascii', 'ignore')
        params['continue_url'] = continue_url
        return self.render_template('%s/materialize/landing/login.html' % self.app.config.get('app_lang'), **params)

    def post(self):
        """
        email: Get the email from POST dict
        password: Get the password from POST dict
        """

        if not self.form.validate():
            _message = _(messages.post_error)
            self.add_message(_message, 'danger')
            return self.get()
        email = self.form.email.data.lower()
        continue_url = self.request.get('continue').encode('ascii', 'ignore')

        try:
            if utils.is_email_valid(email):
                user = self.user_model.get_by_email(email)
                if user:
                    auth_id = user.auth_ids[0]
                else:
                    raise InvalidAuthIdError
            else:
                auth_id = "own:%s" % email
                user = self.user_model.get_by_auth_id(auth_id)
            
            password = self.form.password.data.strip()
            remember_me = True if str(self.request.POST.get('remember_me')) == 'on' else False

            # Password to SHA512
            password = utils.hashing(password, self.app.config.get('salt'))

            # Try to login user with password
            # Raises InvalidAuthIdError if user is not found
            # Raises InvalidPasswordError if provided password
            # doesn't match with specified user
            self.auth.get_user_by_password(
                auth_id, password, remember=remember_me)

            # if user account is not activated, logout and redirect to home
            if (user.activated == False):
                # logout
                self.auth.unset_session()

                # redirect to home with error message
                resend_email_uri = self.uri_for('resend-account-activation', user_id=user.get_id(),
                                                token=self.user_model.create_resend_token(user.get_id()))
                message = _(messages.inactive_account) + ' ' + resend_email_uri
                self.add_message(message, 'danger')
                return self.redirect_to('login')
            else:
                try:
                    user.last_login = utils.get_date_time()
                    user.put()
                except (apiproxy_errors.OverQuotaError, BadValueError):
                    logging.error("Error saving Last Login in datastore")
            

            if self.app.config['log_visit']:
                try:
                    logVisit = models.LogVisit(
                        user=user.key,
                        uastring=self.request.user_agent,
                        ip=self.request.remote_addr,
                        timestamp=utils.get_date_time()
                    )
                    logVisit.put()
                except (apiproxy_errors.OverQuotaError, BadValueError):
                    logging.error("Error saving Visit Log in datastore")
            if continue_url:
                self.redirect(continue_url)
            else:
                message = _(messages.logged).format(user.name)
                self.add_message(message, 'success')                
                return self.redirect_to('landing')
        except (InvalidAuthIdError, InvalidPasswordError), e:
            # Returns error message to self.response.write in
            # the BaseHandler.dispatcher
            message = _(messages.user_pass_mismatch)
            self.add_message(message, 'danger')
            return self.redirect_to('login', continue_url=continue_url) if continue_url else self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        return forms.LoginForm(self)

class MaterializeLogoutRequestHandler(BaseHandler):
    """
    Destroy user session and redirect to login
    """

    def get(self):
        if self.user:
            message = _(messages.logout)
            self.add_message(message, 'info')

        self.auth.unset_session()
        # User is logged out, let's try redirecting to login page
        try:
            self.redirect_to('landing')
        except (AttributeError, KeyError), e:
            logging.error("Error logging out: %s" % e)
            message = _(messages.logout_error)
            self.add_message(message, 'danger')
            return self.redirect_to('landing')

# REGISTER

class MaterializeRegisterReferralHandler(BaseHandler):
    """
    Handler to process the link of referrals for a given user_id
    """

    def get(self, user_id):
        if self.user:
            self.redirect_to('materialize-home')
        user = self.user_model.get_by_id(long(user_id))

        if user is not None:
            params = {
                'captchahtml': captchaBase(self),
                '_username': user.name,
                '_email': user.email,
                'is_referral' : True
            }
            return self.render_template('%s/materialize/landing/register.html' % self.app.config.get('app_lang'), **params)
        else:
            return self.redirect_to('landing')

    def post(self, user_id):
        """ Get fields from POST dict """

        # check captcha
        response = self.request.POST.get('g-recaptcha-response')
        remote_ip = self.request.remote_addr

        cResponse = captcha.submit(
            response,
            self.app.config.get('captcha_private_key'),
            remote_ip)

        if cResponse.is_valid:
            # captcha was valid... carry on..nothing to see here
            pass
        else:
            _message = _(messages.captcha_error)
            self.add_message(_message, 'danger')
            return self.get(user_id)

        if not self.form.validate():
            _message = _(messages.saving_error)
            logging.info("Form did not passed.")
            self.add_message(_message, 'danger')
            return self.get(user_id)
        name = self.form.name.data.strip()
        last_name = self.form.last_name.data.strip()
        email = self.form.email.data.lower()
        username = email
        password = self.form.password.data.strip()


        aUser = self.user_model.get_by_email(email)
        if aUser is not None:
            message = _("Sorry, email %s is already in use." % email)
            self.add_message(message, 'danger')
            return self.redirect_to('landing')


        # Password to SHA512
        password = utils.hashing(password, self.app.config.get('salt'))

        # Passing password_raw=password so password will be hashed
        # Returns a tuple, where first value is BOOL.
        # If True ok, If False no new user is created
        unique_properties = ['username', 'email']
        auth_id = "own:%s" % username
        referred_user = self.auth.store.user_model.create_user(
            auth_id, unique_properties, password_raw=password,
            username=username, name=name, last_name=last_name, email=email,
            ip=self.request.remote_addr
        )

        if not referred_user[0]: #user is a tuple
            if "username" in str(referred_user[1]):
                message = _(messages.username_exists).format(username)
            elif "email" in str(referred_user[1]):
                message = _(messages.email_exists).format(email)
            else:
                message = _(messages.user_exists)
            self.add_message(message, 'danger')
            return self.redirect_to('register-referral',user_id=user_id, _full = True)
        else:
            # User registered successfully
            # But if the user registered using the form, the user has to check their email to activate the account ???
            try:
                if not referred_user[1].activated:
                    # send email
                    subject = _(messages.email_activation_subject)
                    confirmation_url = self.uri_for("account-activation-referral",
                                                    ref_user_id=referred_user[1].get_id(),
                                                    token=self.user_model.create_auth_token(referred_user[1].get_id()),
                                                    user_id =  user_id,
                                                    _full=True)
                    if name != '':
                        _username = str(name)
                    else:
                        _username = str(username)
                    # load email's template
                    template_val = {
                        "app_name": self.brand['app_name'],
                        "username": _username,
                        "confirmation_url": confirmation_url,
                        "brand_email_logo": self.brand['brand_email_logo'],
                        "brand_color": self.brand['brand_color'],
                        "brand_secondary_color": self.brand['brand_secondary_color'],
                        "support_url": self.uri_for("contact", _full=True),
                        "twitter_url": self.app.config.get('twitter_url'),
                        "facebook_url": self.app.config.get('facebook_url'),
						"faq_url": self.uri_for("faq", _full=True)
                    }
                    body_path = "%s/emails/account_activation.txt" % self.app.config.get('app_lang')
                    body = self.jinja2.render_template(body_path, **template_val)

                    email_url = self.uri_for('taskqueue-send-email')
                    taskqueue.add(url=email_url, params={
                        'to': str(email),
                        'subject': subject,
                        'body': body,
                    })

                    
                    #unlock rewards status for the user who referred this referred_user
                    already_invited = False;
                    user = self.user_model.get_by_id(long(user_id))
                    for reward in user.rewards:
                        if reward.content == email:
                            already_invited = True;
                            break

                    if not already_invited:
                        reward = models.Rewards(amount = 0,earned = True, category = 'invite',
                            content = email,timestamp = utils.get_date_time(),status = 'invited')                 
                        user.rewards.append(reward)
                        user.put()

                    message = _(messages.register_success)
                    self.add_message(message, 'success')
                    return self.redirect_to('landing')

                # If the user didn't register using registration form ???
                db_user = self.auth.get_user_by_password(referred_user[1].auth_ids[0], password)

                # Check Twitter association in session
                twitter_helper = twitter.TwitterAuth(self)
                twitter_association_data = twitter_helper.get_association_data()
                if twitter_association_data is not None:
                    if models.SocialUser.check_unique(referred_user[1].key, 'twitter', str(twitter_association_data['id'])):
                        social_user = models.SocialUser(
                            user=referred_user[1].key,
                            provider='twitter',
                            uid=str(twitter_association_data['id']),
                            extra_data=twitter_association_data
                        )
                        social_user.put()

                #check Facebook association
                fb_data = json.loads(self.session['facebook'])
                if fb_data is not None:
                    if models.SocialUser.check_unique(referred_user.key, 'facebook', str(fb_data['id'])):
                        social_user = models.SocialUser(
                            user=referred_user.key,
                            provider='facebook',
                            uid=str(fb_data['id']),
                            extra_data=fb_data
                        )
                        social_user.put()

                #check LinkedIn association
                li_data = json.loads(self.session['linkedin'])
                if li_data is not None:
                    if models.SocialUser.check_unique(referred_user.key, 'linkedin', str(li_data['id'])):
                        social_user = models.SocialUser(
                            user=referred_user.key,
                            provider='linkedin',
                            uid=str(li_data['id']),
                            extra_data=li_data
                        )
                        social_user.put()

                message = _(messages.logged).format(username)
                self.add_message(message, 'success')
                return self.redirect_to('materialize-home')
            except (AttributeError, KeyError), e:
                logging.error('Unexpected error creating the user %s: %s' % (username, e ))
                message = _(messages.user_creation_error).format(username)
                self.add_message(message, 'danger')
                return self.redirect_to('register-referral',user_id=user_id, _full = True)

    @webapp2.cached_property
    def form(self):
        f = forms.RegisterForm(self)
        return f

class MaterializeRegisterRequestHandler(BaseHandler):
    """
    Handler for Sign Up Users
    """

    def get(self):
        """ Returns a simple HTML form for create a new user """

        if self.user:
            self.redirect_to('materialize-home')

        params = {
            'captchahtml': captchaBase(self),
        }
        return self.render_template('%s/materialize/landing/register.html' % self.app.config.get('app_lang'), **params)

    def post(self):
        """ Get fields from POST dict """


        # check captcha
        response = self.request.POST.get('g-recaptcha-response')
        remote_ip = self.request.remote_addr

        cResponse = captcha.submit(
            response,
            self.app.config.get('captcha_private_key'),
            remote_ip)

        if cResponse.is_valid:
            # captcha was valid... carry on..nothing to see here
            pass
        else:
            _message = _(messages.captcha_error)
            self.add_message(_message, 'danger')
            return self.redirect_to('register')

        if not self.form.validate():
            logging.info("Form did not passed.")
            _message = _(messages.saving_error)
            self.add_message(_message, 'danger')
            return self.get()
        name = self.form.name.data.strip()
        last_name = self.form.last_name.data.strip()
        email = self.form.email.data.lower()
        username = email
        password = self.form.password.data.strip()

        #if this is a simple app, no one will be able to register if not invited
        if self.app.config.get('simplify') and not models.SpecialAccess.get_by_email(email):
            message = _(messages.no_access)
            self.add_message(message, 'danger')
            return self.get()


        aUser = self.user_model.get_by_email(email)
        if aUser is not None:
            message = _("Sorry, email %s is already in use." % email)
            self.add_message(message, 'danger')
            return self.redirect_to('landing')

        # Password to SHA512
        password = utils.hashing(password, self.app.config.get('salt'))

        # Passing password_raw=password so password will be hashed
        # Returns a tuple, where first value is BOOL.
        # If True ok, If False no new user is created
        unique_properties = ['username', 'email']
        auth_id = "own:%s" % username
        user = self.auth.store.user_model.create_user(
            auth_id, unique_properties, password_raw=password,
            username=username, name=name, last_name=last_name, email=email,
            ip=self.request.remote_addr
        )

        if not user[0]: #user is a tuple
            if "username" in str(user[1]):
                message = _(messages.username_exists).format(username)
            elif "email" in str(user[1]):
                message = _(messages.email_exists).format(email)
            else:
                message = _(messages.user_exists)
            self.add_message(message, 'danger')
            return self.redirect_to('register')
        else:
            # User registered successfully
            # But if the user registered using the form, the user has to check their email to activate the account ???
            try:
                sa = models.SpecialAccess.get_by_email(user[1].email)
                if sa:
                    user[1].activated = True
                    user[1].role = sa.role
                    user[1].put()
                    # Slack Incoming WebHooks
                    from google.appengine.api import urlfetch            
                    urlfetch.fetch(self.app.config.get('slack_webhook_url'), payload='{"channel": "#general", "username": "webhookbot", "text": "just got a new user at '+self.app.config.get('app_id')+'! Go surprise him at '+user[1].email+'", "icon_emoji": ":bowtie:"}', method='POST')

                if not user[1].activated:
                    # send email
                    #subject = _("%s Account Verification" % self.brand['app_name'])
                    subject = _(messages.email_activation_subject)
                    confirmation_url = self.uri_for("account-activation",
                                                    user_id=user[1].get_id(),
                                                    token=self.user_model.create_auth_token(user[1].get_id()),
                                                    _full=True)

                    # load email's template
                    template_val = {
                        "app_name": self.brand['app_name'],
                        "username": name,
                        "confirmation_url": confirmation_url,
                        "brand_email_logo": self.brand['brand_email_logo'],
                        "brand_color": self.brand['brand_color'],
                        "brand_secondary_color": self.brand['brand_secondary_color'],
                        "support_url": self.uri_for("contact", _full=True),
                        "twitter_url": self.app.config.get('twitter_url'),
                        "facebook_url": self.app.config.get('facebook_url'),
                        "faq_url": self.uri_for("faq", _full=True)
                    }
                    body_path = "%s/emails/account_activation.txt" % self.app.config.get('app_lang')
                    body = self.jinja2.render_template(body_path, **template_val)

                    email_url = self.uri_for('taskqueue-send-email')
                    taskqueue.add(url=email_url, params={
                        'to': str(email),
                        'subject': subject,
                        'body': body,
                    })

                    message = _(messages.register_success)
                    self.add_message(message, 'success')
                    return self.redirect_to('landing')

                # If the user didn't register using registration form ???
                db_user = self.auth.get_user_by_password(user[1].auth_ids[0], password)

                message = _(messages.logged).format(username)
                self.add_message(message, 'success')
                return self.redirect_to('landing')
            except (AttributeError, KeyError), e:
                logging.error('Unexpected error creating the user %s: %s' % (username, e ))
                message = _(messages.user_creation_error).format(username)
                self.add_message(message, 'danger')
                return self.redirect_to('landing')

    @webapp2.cached_property
    def form(self):
        f = forms.RegisterForm(self)
        return f

# ACTIVATION

class MaterializeAccountActivationHandler(BaseHandler):
    """
    Handler for account activation
    """

    def get(self, user_id, token):
        try:
            if not self.user_model.validate_auth_token(user_id, token):
                message = _(messages.used_activation_link)
                self.add_message(message, 'danger')
                return self.redirect_to('login')

            user = self.user_model.get_by_id(long(user_id))
            # activate the user's account
            user.activated = True
            user.last_login = utils.get_date_time()
            
            # create unique url for sharing & referrals purposes
            long_url = self.uri_for("register-referral",user_id=user.get_id(),_full=True)
            logging.info("Long URL: %s" % long_url)
            user.link_referral = long_url
            
            #The goo.gl way:
            # post_url = 'https://www.googleapis.com/urlshortener/v1/url'            
            # payload = {'longUrl': long_url}
            # headers = {'content-type': 'application/json'}
            # r = requests.post(post_url, data=json.dumps(payload), headers=headers)
            # j = json.loads(r.text)
            # logging.info("Google response: %s" % j)
            # short_url = j['id']

            #The bit.ly way:
            if self.app.config.get('has_referrals'):
                api = bitly.Api(login=self.app.config.get('bitly_login'), apikey=self.app.config.get('bitly_apikey'))
                short_url=api.shorten(long_url)
                logging.info("Bitly response: %s" % short_url)
                user.link_referral = short_url

            reward = models.Rewards(amount = 100,earned = True, category = 'configuration',
                content = 'Activation',timestamp = utils.get_date_time(),status = 'completed')                 
            user.rewards.append(reward)

            #Role init
            sa = models.SpecialAccess.get_by_email(user.email)
            if sa:
                user.role = sa.role
            else:
                user.role = 'NA'

            #Datastore allocation
            user.put()

            # Login User
            self.auth.get_user_by_token(int(user_id), token)

            # Delete token
            self.user_model.delete_auth_token(user_id, token)

            # Slack Incoming WebHooks
            from google.appengine.api import urlfetch            
            urlfetch.fetch(self.app.config.get('slack_webhook_url'), payload='{"channel": "#general", "username": "webhookbot", "text": "just got a new user at '+self.app.config.get('app_id')+'! Go surprise him at '+user.email+'", "icon_emoji": ":bowtie:"}', method='POST')

            message = _(messages.activation_success).format(
                user.email)
            self.add_message(message, 'success')
            self.redirect_to('landing')

        except (AttributeError, KeyError, InvalidAuthIdError, NameError), e:
            logging.error("Error activating an account: %s" % e)
            message = _(messages.post_error)
            self.add_message(message, 'danger')
            return self.redirect_to('landing')

class MaterializeAccountActivationReferralHandler(BaseHandler):
    """
    Handler for account activation
    """

    def get(self, ref_user_id, token, user_id):
        try:
            if not self.user_model.validate_auth_token(ref_user_id, token):
                message = _(messages.used_activation_link)
                self.add_message(message, 'danger')
                return self.redirect_to('login')


            user = self.user_model.get_by_id(long(user_id))
            referred_user = self.user_model.get_by_id(long(ref_user_id))
            
            # activate the user's account            
            referred_user.activated = True
            referred_user.last_login = utils.get_date_time()
            
            # create unique url for sharing & referrals purposes
            long_url = self.uri_for("register-referral",user_id=referred_user.get_id(),_full=True)
            logging.info("Long URL: %s" % long_url)
            
            #The goo.gl way:
            # post_url = 'https://www.googleapis.com/urlshortener/v1/url'            
            # payload = {'longUrl': long_url}
            # headers = {'content-type': 'application/json'}
            # r = requests.post(post_url, data=json.dumps(payload), headers=headers)
            # j = json.loads(r.text)
            # logging.info("Google response: %s" % j)
            # short_url = j['id']

            #The bit.ly way:
            api = bitly.Api(login=self.app.config.get('bitly_login'), apikey=self.app.config.get('bitly_apikey'))
            short_url=api.shorten(long_url)
            logging.info("Bitly response: %s" % short_url)


            referred_user.link_referral = short_url
            reward = models.Rewards(amount = 100,earned = True, category = 'configuration',
                content = 'Activation',timestamp = utils.get_date_time(),status = 'completed')                 
            referred_user.rewards.append(reward)
            reward = models.Rewards(amount = 20,earned = True, category = 'invite',
                content = 'Invitee by: ' + user.email,timestamp = utils.get_date_time(),status = 'completed')                 
            referred_user.rewards.append(reward)


            #Role init
            sa = models.SpecialAccess.get_by_email(user.email)
            if sa:
                user.role = sa.role
            else:
                referred_user.role = 'NA'

            #Datastore allocation
            referred_user.put()
            
            # assign the referral reward
            for reward in user.rewards:
                if reward.content == referred_user.email:
                    reward.amount = 50;
                    reward.status = 'joined';
                    user.put()
                    break

            # Login User
            self.auth.get_user_by_token(int(ref_user_id), token)

            # Delete token
            self.user_model.delete_auth_token(ref_user_id, token)

            # Slack Incoming WebHooks
            from google.appengine.api import urlfetch
            urlfetch.fetch(self.app.config.get('slack_webhook_url'), payload='{"channel": "#general", "username": "webhookbot", "text": "Just got a new referred user at '+self.app.config.get('app_id')+'! Go surprise him at '+referred_user.email+' and remember to thank '+ user.email +'", "icon_emoji": ":bowtie:"}', method='POST')


            message = _(messages.activation_success).format(
                referred_user.email)
            self.add_message(message, 'success')
            self.redirect_to('landing')

        except (AttributeError, KeyError, InvalidAuthIdError, NameError), e:
            logging.error("Error activating an account: %s" % e)
            message = _(messages.post_error)
            self.add_message(message, 'danger')
            return self.redirect_to('login')

""" --------------- VISITOR HANDLERS --------------- """

# LANDING

class MaterializeLandingRequestHandler(BaseHandler):
    """
    Handler to show the landing page
    """

    def get(self):
        """ Returns a simple HTML form for landing """
        params = {}
        if not self.user:
            params['captchahtml'] = captchaBase(self)
            if self.app.config.get('simplify'):
                return self.redirect_to('login')
            return self.render_template('%s/materialize/landing/base.html' % self.app.config.get('app_lang'), **params)
        else:
            params, user_info = disclaim(self)            
            if self.app.config.get('simplify'):
                return self.redirect_to('materialize-home')
            return self.render_template('%s/materialize/landing/base.html' % self.app.config.get('app_lang'), **params)

class MaterializeLandingFaqRequestHandler(BaseHandler):
    """
        Handler for materialized frequented asked questions
    """
    def get(self):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {} 
        params['captchahtml'] = captchaBase(self)
        return self.render_template('%s/materialize/landing/faq.html' % self.app.config.get('app_lang'), **params)

class MaterializeLandingTouRequestHandler(BaseHandler):
    """
        Handler for materialized terms of use
    """
    def get(self):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {} 
        params['captchahtml'] = captchaBase(self)
        return self.render_template('%s/materialize/landing/tou.html' % self.app.config.get('app_lang'), **params)

class MaterializeLandingPrivacyRequestHandler(BaseHandler):
    """
        Handler for materialized privacy policy
    """
    def get(self):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {} 
        params['captchahtml'] = captchaBase(self)
        return self.render_template('%s/materialize/landing/privacy.html' % self.app.config.get('app_lang'), **params)

class MaterializeLandingLicenseRequestHandler(BaseHandler):
    """
        Handler for materialized privacy policy
    """
    def get(self):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {} 
        params['captchahtml'] = captchaBase(self)
        return self.render_template('%s/materialize/landing/license.html' % self.app.config.get('app_lang'), **params)

class MaterializeLandingContactRequestHandler(BaseHandler):
    """
        Handler for materialized contact us
    """
    def get(self):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {} 
        params['captchahtml'] = captchaBase(self)
        if self.user:
            user_info = self.user_model.get_by_id(long(self.user_id))
            if user_info.name or user_info.last_name:
                self.form.name.data = user_info.name + " " + user_info.last_name
            if user_info.email:
                self.form.email.data = user_info.email
        params['exception'] = self.request.get('exception')

        params['t'] = str(self.request.get('t')) if len(self.request.get('t')) > 1 else 'no'

        return self.render_template('%s/materialize/landing/contact.html' % self.app.config.get('app_lang'), **params)

    def post(self):
        """ validate contact form """
        if not self.form.validate():
            _message = _(messages.post_error)
            self.add_message(_message, 'danger')
            return self.get()

        import bp_includes.lib.i18n as i18n
        from bp_includes.external import httpagentparser

        remote_ip = self.request.remote_addr
        city = i18n.get_city_code(self.request)
        region = i18n.get_region_code(self.request)
        country = i18n.get_country_code(self.request)
        coordinates = i18n.get_city_lat_long(self.request)
        user_agent = self.request.user_agent
        exception = self.request.POST.get('exception')
        name = self.form.name.data.strip()
        email = self.form.email.data.lower()
        message = self.form.message.data.strip()
        template_val = {
            "name": name,
            "email": email,
            "ip": remote_ip,
            "city": city,
            "region": region,
            "country": country,
            "coordinates": coordinates,
            "message": message,
            "brand_email_logo": self.brand['brand_email_logo'],
            "brand_color": self.brand['brand_color'],
            "brand_secondary_color": self.brand['brand_secondary_color']
        }
        try:
            # parsing user_agent and getting which os key to use
            # windows uses 'os' while other os use 'flavor'
            ua = httpagentparser.detect(user_agent)
            _os = ua.has_key('flavor') and 'flavor' or 'os'

            operating_system = str(ua[_os]['name']) if "name" in ua[_os] else "-"
            if 'version' in ua[_os]:
                operating_system += ' ' + str(ua[_os]['version'])
            if 'dist' in ua:
                operating_system += ' ' + str(ua['dist'])

            browser = str(ua['browser']['name']) if 'browser' in ua else "-"
            browser_version = str(ua['browser']['version']) if 'browser' in ua else "-"

            template_val = {
                "name": name,
                "email": email,
                "ip": remote_ip,
                "city": city,
                "region": region,
                "country": country,
                "coordinates": coordinates,
                "brand_email_logo": self.brand['brand_email_logo'],
                "brand_color": self.brand['brand_color'],
                "brand_secondary_color": self.brand['brand_secondary_color'],
                "browser": browser,
                "browser_version": browser_version,
                "operating_system": operating_system,
                "message": message
            }
        except Exception as e:
            logging.error("error getting user agent info: %s" % e)

        try:
            subject = _(messages.contact_subject)
            # exceptions for error pages that redirect to contact
            if exception != "":
                subject = "{} (Exception error: {})".format(subject, exception)

            body_path = "%s/emails/contact.txt" % self.app.config.get('app_lang')
            body = self.jinja2.render_template(body_path, **template_val)

            email_url = self.uri_for('taskqueue-send-email')
            taskqueue.add(url=email_url, params={
                'to': self.app.config.get('contact_recipient'),
                'subject': subject,
                'body': body,
                'sender': self.app.config.get('contact_sender'),
            })

            message = _(messages.contact_success)
            self.add_message(message, 'success')
            return self.redirect_to('contact')

        except (AttributeError, KeyError), e:
            logging.error('Error sending contact form: %s' % e)
            message = _(messages.post_error)
            self.add_message(message, 'danger')
            return self.redirect_to('contact')

    @webapp2.cached_property
    def form(self):
        return forms.ContactForm(self)

# BLOG

class MaterializeLandingBlogRequestHandler(BaseHandler):
    """
        Handler for materialized privacy policy
    """
    def get(self):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {}        
        params['captchahtml'] = captchaBase(self)
        posts = models.BlogPost.query()
        params['total'] = posts.count()
        params['posts'] = []
        for post in posts:
            categories = ""
            for category in post.category:
                categories += str(category) + ", "
            params['posts'].append((post.key.id(), post.updated.strftime("%Y-%m-%d"), post.title, post.subtitle, post.blob_key, post.author, post.brief, categories[0:-2]))
        return self.render_template('%s/materialize/landing/blog.html' % self.app.config.get('app_lang'), **params)

class MaterializeLandingBlogPostRequestHandler(BaseHandler):
    """
        Handler for materialized privacy policy
    """
    def get(self, post_id):
        """ returns simple html for a get request """
        if self.user_id:
            params, user_info = disclaim(self)
        else:
            params = {} 
        params['captchahtml'] = captchaBase(self)
        blog = models.BlogPost.get_by_id(long(post_id))
        if blog is not None:
            params['title'] = blog.title
            params['subtitle'] = blog.subtitle
            params['blob_key'] = blog.blob_key
            params['author'] = blog.author
            params['content'] = blog.content
            return self.render_template('%s/materialize/landing/blogpost.html' % self.app.config.get('app_lang'), **params)
        else:
            return self.error(404)

""" --------------- USER HANDLERS --------------- """

# SETTINGS

class MaterializeSettingsProfileRequestHandler(BaseHandler):
    """
        Handler for materialized settings profile
    """
    @user_required
    def get(self):
        """ returns simple html for a get request """
        params, user_info = disclaim(self)
        if not params['address_from']:
            params['address_from'] = ""
        params['google_clientID'] = self.app.config.get('google_clientID')
        params['facebook_appID'] = self.app.config.get('facebook_appID')
        params['google_maps_key'] = self.app.config.get('google_maps_key')
        params['user'] = user_info
        params['captchahtml'] = captchaBase(self)
        for auth_id in user_info.auth_ids:
            logging.info("auth id: %s" % auth_id)
        return self.render_template('%s/materialize/users/settings/profile.html' % self.app.config.get('app_lang'), **params)

    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            message = _(messages.saving_error)
            self.add_message(message, 'danger')
            return self.get()
        name = self.request.get('name')
        last_name = self.request.get('last_name')
        gender = self.request.get('gender')
        phone = self.request.get('phone')
        birth = self.request.get('birth')
        address_from = self.request.get('address_from')
        address_from_coord = self.request.get('address_from_coord')
        picture = self.request.get('picture') if len(self.request.get('picture'))>1 else None

        try:
            user_info = self.user_model.get_by_id(long(self.user_id))

            try:
                message = ''
                user_info.name = name
                user_info.last_name = last_name
                if (len(birth) > 9):
                    user_info.birth = date(int(birth[:4]), int(birth[5:7]), int(birth[8:]))
                if 'male' in gender:
                    user_info.gender = gender
                user_info.phone = phone
                if picture is not None:
                    user_info.picture = images.resize(picture, width=180, height=180, crop_to_fit=True, quality=100)
                if address_from is not None:
                    user_info.address = models.Address()
                    user_info.address.address_from = address_from
                    if len(address_from_coord.split(',')) == 2:
                        user_info.address.address_from_coord = ndb.GeoPt(address_from_coord)
                user_info.put()
                message += " " + _(messages.saving_success)
                self.add_message(message, 'success')
                return self.get()

            except (AttributeError, KeyError, ValueError), e:
                logging.error('Error updating profile: %s ' % e)
                message = _(messages.saving_error)
                self.add_message(message, 'danger')
                return self.get()

        except (AttributeError, TypeError), e:
            login_error_message = _(messages.expired_session)
            logging.error('Error updating profile: %s' % e)
            self.add_message(login_error_message, 'danger')
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        f = forms.SettingsProfileForm(self)
        return f

class MaterializeSettingsEmailRequestHandler(BaseHandler):
    """
        Handler for materialized settings email
    """
    @user_required
    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            _message = _(messages.saving_error)
            self.add_message(_message, 'danger')
            return self.redirect_to('materialize-settings-profile')
        new_email = self.form.new_email.data.strip()
        password = self.form.password.data.strip()

        try:
            user_info = self.user_model.get_by_id(long(self.user_id))
            auth_id = "own:%s" % user_info.username
            # Password to SHA512
            password = utils.hashing(password, self.app.config.get('salt'))

            try:
                # authenticate user by its password
                user = self.user_model.get_by_auth_password(auth_id, password)

                # if the user change his/her email address
                if new_email != user.email:

                    # check whether the new email has been used by another user
                    aUser = self.user_model.get_by_email(new_email)
                    if aUser is not None:
                        message = _("Sorry, email %s is already in use." % new_email)
                        self.add_message(message, 'danger')
                        return self.redirect_to('materialize-settings-account')

                    # send email
                    subject = _(messages.email_emailchanged_subject)
                    user_token = self.user_model.create_auth_token(self.user_id)
                    confirmation_url = self.uri_for("materialize-email-changed-check",
                                                    user_id=user_info.get_id(),
                                                    encoded_email=utils.encode(new_email),
                                                    token=user_token,
                                                    _full=True)
                    if user.name != '':
                        _username = user.name
                    else:
                        _username = user.email
                    # load email's template
                    template_val = {
                        "app_name": self.brand['app_name'],
                        "username": _username,
                        "new_email": new_email,
                        "confirmation_url": confirmation_url,
                        "brand_email_logo": self.brand['brand_email_logo'],
                        "brand_color": self.brand['brand_color'],
                        "brand_secondary_color": self.brand['brand_secondary_color'],
                        "support_url": self.uri_for("contact", _full=True),
                        "twitter_url": self.app.config.get('twitter_url'),
                        "facebook_url": self.app.config.get('facebook_url'),
                        "faq_url": self.uri_for("faq", _full=True)
                    }

                    old_body_path = "%s/emails/email_changed_notification_old.txt" % self.app.config.get('app_lang')
                    old_body = self.jinja2.render_template(old_body_path, **template_val)

                    new_body_path = "%s/emails/email_changed_notification_new.txt" % self.app.config.get('app_lang')
                    new_body = self.jinja2.render_template(new_body_path, **template_val)

                    email_url = self.uri_for('taskqueue-send-email')
                    taskqueue.add(url=email_url, params={
                        'to': user.email,
                        'subject': subject,
                        'body': old_body,
                    })
                    taskqueue.add(url=email_url, params={
                        'to': new_email,
                        'subject': subject,
                        'body': new_body,
                    })

                    # display successful message
                    msg = _(messages.emailchanged_success)
                    self.add_message(msg, 'success')
                    return self.redirect_to('materialize-settings-profile')

                else:
                    self.add_message(_(messages.emailchanged_error), "warning")
                    return self.redirect_to('materialize-settings-profile')


            except (InvalidAuthIdError, InvalidPasswordError), e:
                # Returns error message to self.response.write in
                # the BaseHandler.dispatcher
                message = _(messages.password_wrong)
                self.add_message(message, 'danger')
                return self.redirect_to('materialize-settings-profile')

        except (AttributeError, TypeError), e:
            login_error_message = _(messages.expired_session)
            self.add_message(login_error_message, 'danger')
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        return forms.EditEmailForm(self)

class MaterializeSettingsReferralsRequestHandler(BaseHandler):
    """
        Handler for materialized settings referrals
    """
    @user_required
    def get(self):
        """ returns simple html for a get request """
        params, user_info = disclaim(self)
        params['referrals'] = []
        rewards = user_info.rewards
        rewards.reverse
        unique_emails = []
        page = 1
        if self.request.get('p') != '':
            page = 1 + int(self.request.get('p'))
        offset = (page - 1)*51
        last = page*51
        if last > len(rewards):
            last = len(rewards)
        for i in range(offset, last):
            if 'invite' in rewards[i].category and rewards[i].content != '' and rewards[i].content not in unique_emails:
                params['referrals'].append(rewards[i])
                unique_emails.append(rewards[i].content)
                if rewards[i].status == 'invited':
                    aUser = self.user_model.get_by_email(rewards[i].content)
                    if aUser is not None:
                        params['referrals'][params['referrals'].index(rewards[i])].status = 'inelegible'

        params['page'] = page
        params['last_page'] = int(len(rewards)/50)
        params['total'] = len(params['referrals'])
        params['grand_total'] = int(len(rewards))
        params['properties'] = ['timestamp','content','status']

        p = self.request.get('p')
        c = self.request.get('c')
        forward = True if p not in ['prev'] else False
        cursor = Cursor(urlsafe=c)

        recipients =  models.Reward.query( ndb.AND(models.Reward.referrer_id == long(self.user_id), models.Reward.category == 'invite') )
        count = recipients.count()
        PAGE_SIZE = 30
        if forward:
            recipients, next_cursor, more = recipients.order(-models.Reward.created, models.Reward.key).fetch_page(PAGE_SIZE, start_cursor=cursor)
            if next_cursor and more:
                self.view.next_cursor = next_cursor
            if c:
                self.view.prev_cursor = cursor.reversed()
        else:
            recipients, next_cursor, more = recipients.order(models.Reward.created, models.Reward.key).fetch_page(PAGE_SIZE, start_cursor=cursor)
            recipients = list(reversed(recipients))
            if next_cursor and more:
                self.view.prev_cursor = next_cursor
            self.view.next_cursor = cursor.reversed()

        def pager_url(p, cursor):
            params = OrderedDict()
            if cursor:
                params['c'] = cursor.urlsafe()
            return self.uri_for('materialize-settings-referrals', **params)

        self.view.pager_url = pager_url

        params['recipients'] = recipients
        params['count'] = count
        params['page_size'] = PAGE_SIZE
        return self.render_template('%s/materialize/users/settings/referrals.html' % self.app.config.get('app_lang'), **params)


    def post(self):
        """ Get fields from POST dict """
        user_info = self.user_model.get_by_id(long(self.user_id))
        message = ''

        if not self.form.validate():
            message += messages.saving_error
            self.add_message(message, 'error')
            return self.get()

        _emails = self.form.emails.data.replace('"','').replace('[','').replace(']','')
        logging.info("Referrals' email addresses: %s" % _emails)

        try:
            # send email
            subject = _(messages.email_referral_subject)
            if user_info.name != '':
                _username = user_info.name
            else:
                _username = user_info.username
             # load email's template
            template_val = {
                "app_name": self.brand['app_name'],
                "user_email": user_info.email,
                "user_name": _username,
                "link_referral" : user_info.link_referral,
                "brand_email_logo": self.brand['brand_email_logo'],
                "brand_color": self.brand['brand_color'],
                "brand_secondary_color": self.brand['brand_secondary_color'],
                "support_url": self.uri_for("contact", _full=True),
                "twitter_url": self.app.config.get('twitter_url'),
                "facebook_url": self.app.config.get('facebook_url'),
                "faq_url": self.uri_for("faq", _full=True)
            }
            body_path = "%s/emails/referrals.txt" % self.app.config.get('app_lang')
            body = self.jinja2.render_template(body_path, **template_val)

            email_url = self.uri_for('taskqueue-send-email')
            _email = _emails.split(",")

            for _email_ in _email:
                taskqueue.add(url=email_url, params={
                    'to': str(_email_),
                    'subject': subject,
                    'body': body,
                })
                reward = models.Rewards(amount = 0,earned = True, category = 'invite',content = _email_,
                                        timestamp = utils.get_date_time(),status = 'invited')    
                
                edited_userinfo = False
                for rewards in user_info.rewards:
                    if 'invite' in rewards.category and rewards.content == reward.content:
                        user_info.rewards[user_info.rewards.index(rewards)] = reward
                        edited_userinfo = True
                if not edited_userinfo:
                    user_info.rewards.append(reward)

                user_info.put()

            message += " " + _(messages.invite_success)
            self.add_message(message, 'success')
            return self.get()
           
        except (KeyError, AttributeError), e:
            logging.error("Error resending invitation email: %s" % e)
            message = _(messages.post_error)
            self.add_message(message, 'danger')
            return self.redirect_to('home')

          
    @webapp2.cached_property
    def form(self):
        f = forms.ReferralsForm(self)
        return f

class MaterializeEmailChangedCompleteHandler(BaseHandler):
    """
    Handler for completed email change
    Will be called when the user click confirmation link from email
    """

    @user_required
    def get(self, user_id, encoded_email, token):
        verify = self.user_model.get_by_auth_token(int(user_id), token)
        email = utils.decode(encoded_email)
        if verify[0] is None:
            message = _(messages.used_activation_link)
            self.add_message(message, 'warning')
            self.redirect_to('materialize-home')

        else:
            # save new email
            user = verify[0]
            x = ndb.Key("Unique", "User.username:%s" % user.email).get()
            y = ndb.Key("Unique", "User.auth_id:own:%s" % user.email).get()
            z = ndb.Key("Unique", "User.email:%s" % user.email).get()
            ndb.Key("Unique", "User.username:%s" % user.email).delete_async()
            ndb.Key("Unique", "User.auth_id:own:%s" % user.email).delete_async()
            ndb.Key("Unique", "User.email:%s" % user.email).delete_async()

            for i in range(0,len(user.auth_ids)):
                if user.auth_ids[i] == "own:%s" % user.email:
                    user.auth_ids[i] = "own:%s" % email
                    break
            user.email = email
            user.username = email
            user.put()

            x.key = ndb.Key("Unique", "User.username:%s" % user.email)
            y.key = ndb.Key("Unique", "User.auth_id:own:%s" % user.email)
            z.key = ndb.Key("Unique", "User.email:%s" % user.email)
            x.put()
            y.put()
            z.put()


            # delete token
            self.user_model.delete_auth_token(int(user_id), token)
            # add successful message and redirect
            message = _(messages.emailchanged_confirm)
            self.add_message(message, 'success')
            self.redirect_to('materialize-home')

class MaterializeSettingsPasswordRequestHandler(BaseHandler):
    """
        Handler for materialized settings password
    """
    @user_required
    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            self.add_message(_(messages.passwords_mismatch), 'danger')
            return self.redirect_to('materialize-settings-profile')

        current_password = self.form.current_password.data.strip()
        password = self.form.password.data.strip()

        try:
            user_info = self.user_model.get_by_id(long(self.user_id))
            auth_id = "own:%s" % user_info.username

            # Password to SHA512
            current_password = utils.hashing(current_password, self.app.config.get('salt'))
            try:
                user = self.user_model.get_by_auth_password(auth_id, current_password)
                # Password to SHA512
                password = utils.hashing(password, self.app.config.get('salt'))
                user.password = security.generate_password_hash(password, length=12)
                user.put()

                # send email
                subject = messages.email_passwordchanged_subject
                if user.name != '':
                    _username = user.name
                else:
                    _username = user.email
                # load email's template
                template_val = {
                    "app_name": self.brand['app_name'],
                    "username": _username,
                    "email": user.email,
                    "reset_password_url": self.uri_for("password-reset", _full=True),
                    "brand_email_logo": self.brand['brand_email_logo'],
                    "brand_color": self.brand['brand_color'],
                    "brand_secondary_color": self.brand['brand_secondary_color'],
                    "support_url": self.uri_for("contact", _full=True),
                    "twitter_url": self.app.config.get('twitter_url'),
                    "facebook_url": self.app.config.get('facebook_url'),
                    "faq_url": self.uri_for("faq", _full=True)
                }
                email_body_path = "%s/emails/password_changed.txt" % self.app.config.get('app_lang')
                email_body = self.jinja2.render_template(email_body_path, **template_val)
                email_url = self.uri_for('taskqueue-send-email')
                taskqueue.add(url=email_url, params={
                    'to': user.email,
                    'subject': subject,
                    'body': email_body,
                    'sender': self.app.config.get('contact_sender'),
                })

                #Login User
                self.auth.get_user_by_password(user.auth_ids[0], password)
                self.add_message(_(messages.passwordchange_success), 'success')
                return self.redirect_to('materialize-settings-profile')
            except (InvalidAuthIdError, InvalidPasswordError), e:
                # Returns error message to self.response.write in
                # the BaseHandler.dispatcher
                message = _(messages.password_wrong)
                self.add_message(message, 'danger')
                return self.redirect_to('materialize-settings-profile')
        except (AttributeError, TypeError), e:
            login_error_message = _(messages.expired_session)
            self.add_message(login_error_message, 'danger')
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        return forms.EditPasswordForm(self)

class MaterializeSettingsDeleteRequestHandler(BaseHandler):
    """
        Handler for materialized settings delete account
    """
    @user_required
    def post(self, **kwargs):
        # check captcha
        response = self.request.POST.get('g-recaptcha-response')
        remote_ip = self.request.remote_addr

        cResponse = captcha.submit(
            response,
            self.app.config.get('captcha_private_key'),
            remote_ip)

        if cResponse.is_valid:
            # captcha was valid... carry on..nothing to see here
            pass
        else:
            _message = _(messages.captcha_error)
            self.add_message(_message, 'danger')
            return self.redirect_to('materialize-settings-profile')

        if not self.form.validate():
            message = _(messages.password_wrong)
            self.add_message(message, 'danger')
            return self.redirect_to('materialize-settings-profile')

        password = self.form.password.data.strip()

        try:

            user_info = self.user_model.get_by_id(long(self.user_id))
            auth_id = "own:%s" % user_info.username
            password = utils.hashing(password, self.app.config.get('salt'))

            try:
                # authenticate user by its password
                user = self.user_model.get_by_auth_password(auth_id, password)
                if user:
                    # Delete Social Login
                    # for social in models_boilerplate.SocialUser.get_by_user(user_info.key):
                    #     social.key.delete()

                    user_info.key.delete()

                    ndb.Key("Unique", "User.username:%s" % user.username).delete_async()
                    ndb.Key("Unique", "User.auth_id:own:%s" % user.username).delete_async()
                    ndb.Key("Unique", "User.email:%s" % user.email).delete_async()

                    #TODO: Delete UserToken objects, Delete Home if Admin

                    self.auth.unset_session()

                    # display successful message
                    msg = _(messages.account_delete_success)
                    self.add_message(msg, 'success')
                    return self.redirect_to('materialize-home')
                else:
                    message = _(messages.password_wrong)
                    self.add_message(message, 'danger')
                    return self.redirect_to('materialize-settings-profile')

            except (InvalidAuthIdError, InvalidPasswordError), e:
                # Returns error message to self.response.write in
                # the BaseHandler.dispatcher
                message = _(messages.password_wrong)
                self.add_message(message, 'danger')
                return self.redirect_to('materialize-settings-profile')

        except (AttributeError, TypeError), e:
            login_error_message = _(messages.expired_session)
            self.add_message(login_error_message, 'danger')
            self.redirect_to('landing')

    @webapp2.cached_property
    def form(self):
        return forms.DeleteAccountForm(self)

class MaterializeSettingsSocialRequestHandler(BaseHandler):
    @user_required
    def post(self):
        _user_id = int(self.request.get('user_id'))

        if not self.user_id or int(self.user_id) != _user_id:
            self.abort(403)

        reportDict = {}

        kind = self.request.get('kind')
        first_name = self.request.get('first_name')
        last_name = self.request.get('last_name')
        gender = self.request.get('gender')
        picture = self.request.get('picture')
        cover = self.request.get('cover')
        social_id = self.request.get('id')

        try:
            if kind == 'google':
                social = models.UserGOOG.query(models.UserGOOG.user_id == _user_id).get()
                if social is None:
                    social = models.UserGOOG()
                if social_id != 'none':
                    user_info = self.user_model.get_by_id(long(self.user_id))
                    user_info.google_ID = str(social_id)
                    user_info.put()

            if kind == 'facebook':
                social = models.UserFB.query(models.UserFB.user_id == _user_id).get()
                if social is None:
                    social = models.UserFB()
                if social_id != 'none':
                    user_info = self.user_model.get_by_id(long(self.user_id))
                    user_info.facebook_ID = str(social_id)
                    user_info.put()
                age_range = self.request.get('age_range')
                social.age_range = int(age_range) if age_range != 'none' else social.age_range

            social.user_id = _user_id

            social.first_name = first_name if first_name != 'none' else social.first_name
            social.last_name = last_name if last_name != 'none' else social.last_name
            social.gender = gender if gender != 'none' else social.gender
            social.picture = picture if picture != 'none' else social.picture
            social.cover = cover if cover != 'none' else social.cover
            social.put()
            reportDict['status'] = 'success'
            reportDict['contents'] = 'user social profile for kind %s has been saved' % kind

        except Exception as e:
            reportDict['status'] = 'error'
            reportDict['contents'] = '%s' % e
            pass

        self.response.headers.add_header("Access-Control-Allow-Origin", "*")
        self.response.headers['Content-Type'] = 'application/json'
        self.response.write(json.dumps(reportDict))

# USER SECTIONS

class MaterializeHomeRequestHandler(BaseHandler):
    """
    Handler for materialized home
    """
    @user_required
    def get(self):
        """ Returns a simple HTML form for materialize home """
        ####-------------------- R E D I R E C T I O N S --------------------####
        if not self.user:
            return self.redirect_to('login')
        ####------------------------------------------------------------------####

        ####-------------------- P R E P A R A T I O N S --------------------####
        params, user_info = disclaim(self)
        ####------------------------------------------------------------------####

        params['contents'] = models.Content.query(models.Content.hidden == False)
        params['user_permission'] = user_info.level
        
        return self.render_template('%s/materialize/users/sections/home.html' % self.app.config.get('app_lang'), **params)

class MaterializeDemosRequestHandler(BaseHandler):
    """
    Handler for materialized home
    """
    @user_required
    def get(self):
        """ Returns a simple HTML form for materialize home """
        ####-------------------- R E D I R E C T I O N S --------------------####
        if not self.user:
            return self.redirect_to('login')
        ####------------------------------------------------------------------####

        ####-------------------- P R E P A R A T I O N S --------------------####
        params, user_info = disclaim(self)
        ####------------------------------------------------------------------####

        params['google_speech_key'] = self.app.config.get('google_speech_key')
        params['google_maps_key'] = self.app.config.get('google_maps_key')
        params['google_nlp_key'] = self.app.config.get('google_nlp_key')
        params['google_vision_key'] = self.app.config.get('google_vision_key')
        import bp_includes.lib.i18n as i18n
        params['coordinates']= i18n.get_city_lat_long(self.request)
        
        return self.render_template('%s/materialize/users/sections/demos.html' % self.app.config.get('app_lang'), **params)

class MaterializeDemosNLPRequestHandler(BaseHandler):
    """
    Handler for materialized home
    """
    @user_required
    def get(self):
        """ Returns a simple HTML form for materialize home """
        ####-------------------- R E D I R E C T I O N S --------------------####
        if not self.user:
            return self.redirect_to('login')
        ####------------------------------------------------------------------####

        ####-------------------- P R E P A R A T I O N S --------------------####
        params, user_info = disclaim(self)
        ####------------------------------------------------------------------####

        params['google_speech_key'] = self.app.config.get('google_speech_key')
        params['google_maps_key'] = self.app.config.get('google_maps_key')
        params['google_nlp_key'] = self.app.config.get('google_nlp_key')
        params['google_vision_key'] = self.app.config.get('google_vision_key')
        import bp_includes.lib.i18n as i18n
        params['coordinates']= i18n.get_city_lat_long(self.request)
        
        return self.render_template('%s/materialize/users/sections/demos_nlp.html' % self.app.config.get('app_lang'), **params)


class MaterializeReferralsRequestHandler(BaseHandler):
    """
        Handler for materialized referrals
    """
    @user_required
    def get(self):
        """ returns simple html for a get request """
        params, user_info = disclaim(self)

        if not user_info.link_referral:
            # create unique url for sharing & referrals purposes
            long_url = self.uri_for("register-referral",user_id=user_info.get_id(),_full=True)
            logging.info("Long URL: %s" % long_url)
            user_info.link_referral = long_url
            
            #The goo.gl way:
            # post_url = 'https://www.googleapis.com/urlshortener/v1/url'            
            # payload = {'longUrl': long_url}
            # headers = {'content-type': 'application/json'}
            # r = requests.post(post_url, data=json.dumps(payload), headers=headers)
            # j = json.loads(r.text)
            # logging.info("Google response: %s" % j)
            # short_url = j['id']

            #The bit.ly way:
            if self.app.config.get('has_referrals'):
                api = bitly.Api(login=self.app.config.get('bitly_login'), apikey=self.app.config.get('bitly_apikey'))
                short_url=api.shorten(long_url)
                logging.info("Bitly response: %s" % short_url)
                user_info.link_referral = short_url

            user_info.put()
            params['link_referral'] = user_info.link_referral

        params['google_clientID'] = self.app.config.get('google_clientID')
        return self.render_template('%s/materialize/users/sections/referrals.html' % self.app.config.get('app_lang'), **params)

    def post(self):
        """ Get fields from POST dict """
        user_info = self.user_model.get_by_id(long(self.user_id))
        message = ''

        if not self.form.validate():
            message += messages.saving_error
            self.add_message(message, 'danger')
            return self.get()

        _emails = self.form.emails.data.replace('"','').replace('[','').replace(']','')
        logging.info("Referrals' email addresses: %s" % _emails)

        try:
            # send email
            subject = _(messages.email_referral_subject)
            if user_info.name != '':
                _username = user_info.name
            else:
                _username = user_info.username
             # load email's template
            template_val = {
                "app_name": self.brand['app_name'],
                "user_email": user_info.email,
                "user_name": _username,
                "link_referral" : user_info.link_referral,
                "brand_email_logo": self.brand['brand_email_logo'],
                "brand_color": self.brand['brand_color'],
                "brand_secondary_color": self.brand['brand_secondary_color'],
                "support_url": self.uri_for("contact", _full=True),
                "twitter_url": self.app.config.get('twitter_url'),
                "facebook_url": self.app.config.get('facebook_url'),
                "faq_url": self.uri_for("faq", _full=True)
            }
            body_path = "%s/emails/referrals.txt" % self.app.config.get('app_lang')
            body = self.jinja2.render_template(body_path, **template_val)

            email_url = self.uri_for('taskqueue-send-email')
            _email = _emails.split(",")
            _email = list(set(_email)) #removing duplicates

            for _email_ in _email:

                aUser = self.user_model.get_by_email(_email_)
                if aUser is not None:
                    reward = models.Rewards(amount = 0,earned = True, category = 'invite',content = _email_,
                                            timestamp = utils.get_date_time(),status = 'inelegible')                 
                    edited_userinfo = False
                    for rewards in user_info.rewards:
                        if 'invite' in rewards.category and rewards.content == reward.content:
                            user_info.rewards[user_info.rewards.index(rewards)] = reward
                            edited_userinfo = True
                    if not edited_userinfo:
                        user_info.rewards.append(reward)
                else:
                    taskqueue.add(url=email_url, params={
                        'to': str(_email_),
                        'subject': subject,
                        'body': body,
                    })
                    logging.info('Sent referral invitation to %s' % str(_email_))
                    reward = models.Rewards(amount = 0,earned = True, category = 'invite',content = _email_,
                                            timestamp = utils.get_date_time(),status = 'invited')                 
                    edited_userinfo = False
                    for rewards in user_info.rewards:
                        if 'invite' in rewards.category and rewards.content == reward.content:
                            user_info.rewards[user_info.rewards.index(rewards)] = reward
                            edited_userinfo = True
                    if not edited_userinfo:
                        user_info.rewards.append(reward)
                    
            user_info.put()

            message += " " + _(messages.invite_success)
            self.add_message(message, 'success')
            return self.get()
           
        except (KeyError, AttributeError), e:
            logging.error("Error resending invitation email: %s" % e)
            message = _(messages.post_error)
            self.add_message(message, 'danger')
            return self.redirect_to('home')

          
    @webapp2.cached_property
    def form(self):
        f = forms.ReferralsForm(self)
        return f

""" --------------- MEDIA HANDLERS --------------- """

class MediaDownloadHandler(BaseHandler):
    """
    Handler for Serve Vendor's Logo
    """
    def get(self, kind, media_id):
        """ Handles download"""

        params = {}

        if kind == 'profile':
            user_info = self.user_model.get_by_id(long(media_id))        
            if user_info != None:
                if user_info.picture != None:
                    self.response.headers['Content-Type'] = 'image/png'
                    self.response.out.write(user_info.picture)


        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write('No image')

class BlobFormHandler(BaseHandler, blobstore_handlers.BlobstoreUploadHandler):
    """
        To better handle text inputs included in same file form, please refer to bp_admin/blog.py
    """
    @user_required
    def get(self):
        upload_url = blobstore.create_upload_url('/blobstore/upload/')
        self.response.out.write('<html><body>')
        self.response.out.write('<form action="%s" method="POST" enctype="multipart/form-data">' % upload_url)
        self.response.out.write('''Upload File: <input type="file" name="file"><br> <input type="submit"
            name="submit" value="Submit"> <input type="hidden" name="_csrf_token" value="%s"> </form></body></html>''' % self.session.get('_csrf_token'))

class BlobUploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        try:
            upload = self.get_uploads()[0]
            user_photo = models.Media(blob_key=upload.key())
            #photo_url = images.get_serving_url(upload.key())
            user_photo.put()
            self.redirect('/blobstore/serve/%s' % upload.key())
        except:
            self.error(404)

class BlobDownloadHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, photo_key):
        if not blobstore.get(photo_key):
            self.error(404)
        else:
            self.send_blob(photo_key)

""" --------------- SEO HANDLERS --------------- """
class RobotsHandler(BaseHandler):
    def get(self):
        params = {
            'scheme': self.request.scheme,
            'host': self.request.host,
        }
        self.response.headers['Content-Type'] = 'text/plain'

        def set_variables(text, key):
            return text.replace("{{ %s }}" % key, params[key])

        self.response.write(reduce(set_variables, params, open("bp_content/themes/%s/templates/seo/robots.txt" % self.get_theme).read()))

class HumansHandler(BaseHandler):
    def get(self):
        params = {
            'scheme': self.request.scheme,
            'host': self.request.host,
        }
        self.response.headers['Content-Type'] = 'text/plain'

        def set_variables(text, key):
            return text.replace("{{ %s }}" % key, params[key])

        self.response.write(reduce(set_variables, params, open("bp_content/themes/%s/templates/seo/humans.txt" % self.get_theme).read()))

class SitemapHandler(BaseHandler):
    def get(self):
        params = {
            'scheme': self.request.scheme,
            'host': self.request.host,
        }
        self.response.headers['Content-Type'] = 'application/xml'

        def set_variables(text, key):
            return text.replace("{{ %s }}" % key, params[key])

        self.response.write(reduce(set_variables, params, open("bp_content/themes/%s/templates/seo/sitemap.xml" % self.get_theme).read()))

class CrossDomainHandler(BaseHandler):
    def get(self):
        params = {
            'scheme': self.request.scheme,
            'host': self.request.host,
        }
        self.response.headers['Content-Type'] = 'application/xml'

        def set_variables(text, key):
            return text.replace("{{ %s }}" % key, params[key])

        self.response.write(reduce(set_variables, params, open("bp_content/themes/%s/templates/seo/crossdomain.xml" % self.get_theme).read()))
