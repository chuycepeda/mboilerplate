"""
Using redirect route instead of simple routes since it supports strict_slash
Simple route: http://webapp-improved.appspot.com/guide/routing.html#simple-routes
RedirectRoute: http://webapp-improved.appspot.com/api/webapp2_extras/routes.html#webapp2_extras.routes.RedirectRoute
"""
from webapp2_extras.routes import RedirectRoute
from bp_includes import handlers as handlers

secure_scheme = 'https'

_routes = [
    RedirectRoute('/_ah/login_required', handlers.LoginRequiredHandler),
    

    # Landing
    RedirectRoute('/', handlers.MaterializeLandingRequestHandler, name='materialize-landing', strict_slash=True),   
    RedirectRoute('/contact/', handlers.MaterializeLandingContactRequestHandler, name='mat-contact', strict_slash=True),
    RedirectRoute('/faq/', handlers.MaterializeLandingFaqRequestHandler, name='mat-faq', strict_slash=True),
    RedirectRoute('/tou/', handlers.MaterializeLandingTouRequestHandler, name='mat-tou', strict_slash=True),
    RedirectRoute('/privacy/', handlers.MaterializeLandingPrivacyRequestHandler, name='mat-privacy', strict_slash=True),
    RedirectRoute('/register/', handlers.MaterializeRegisterRequestHandler, name='materialize-register', strict_slash=True),
    RedirectRoute('/login/', handlers.MaterializeLoginRequestHandler, name='materialize-login', strict_slash=True),
    RedirectRoute('/logout/', handlers.MaterializeLogoutRequestHandler, name='materialize-logout', strict_slash=True),
    RedirectRoute('/activation/<user_id>/<token>', handlers.MaterializeAccountActivationHandler, name='materialize-account-activation', strict_slash=True),
    RedirectRoute('/social_login/<provider_name>', handlers.SocialLoginHandler, name='social-login', strict_slash=True),
    RedirectRoute('/social_login/<provider_name>/complete', handlers.CallbackSocialLoginHandler, name='social-login-complete', strict_slash=True),
    RedirectRoute('/social_login/<provider_name>/delete', handlers.DeleteSocialProviderHandler, name='delete-social-provider', strict_slash=True),
    RedirectRoute('/resend/<user_id>/<token>', handlers.ResendActivationEmailHandler, name='resend-account-activation', strict_slash=True),
    RedirectRoute('/password-reset/', handlers.PasswordResetHandler, name='password-reset', strict_slash=True),
    RedirectRoute('/password-reset/<user_id>/<token>', handlers.PasswordResetCompleteHandler, name='password-reset-check', strict_slash=True),
    RedirectRoute('/referral/<user_id>/', handlers.RegisterReferralHandler, name='referral', strict_slash=True),
    RedirectRoute('/activation/<ref_user_id>/<token>/<user_id>', handlers.AccountActivationReferralHandler, name='account-activation-referral', strict_slash=True),
    #RedirectRoute('/resend/<ref_user_id>/<token>/<user_id>', handlers.ResendActivationEmailReferralHandler, name='resend-account-activation-referral', strict_slash=True),
    
    # User
    RedirectRoute('/user/home/', handlers.MaterializeHomeRequestHandler, name='materialize-home', strict_slash=True),
    RedirectRoute('/user/inbox/', handlers.MaterializeInboxRequestHandler, name='materialize-inbox', strict_slash=True),
    RedirectRoute('/user/referrals/', handlers.MaterializeReferralsRequestHandler, name='materialize-referrals', strict_slash=True),
    RedirectRoute('/user/setup/home/', handlers.MaterializeSetupHomeRequestHandler, name='materialize-setup-home', strict_slash=True),
    RedirectRoute('/user/settings/profile/', handlers.MaterializeSettingsProfileRequestHandler, name='materialize-settings-profile', strict_slash=True),
    RedirectRoute('/user/settings/home/', handlers.MaterializeSettingsHomeRequestHandler, name='materialize-settings-home', strict_slash=True),
    RedirectRoute('/user/settings/email/', handlers.MaterializeSettingsEmailRequestHandler, name='materialize-settings-email', strict_slash=True),
    RedirectRoute('/user/settings/password/', handlers.MaterializeSettingsPasswordRequestHandler, name='materialize-settings-password', strict_slash=True),
    RedirectRoute('/user/settings/delete/', handlers.MaterializeSettingsDeleteRequestHandler, name='materialize-settings-delete', strict_slash=True),
    RedirectRoute('/user/settings/referrals/', handlers.MaterializeSettingsReferralsRequestHandler, name='materialize-settings-referrals', strict_slash=True),
    RedirectRoute('/user/faq/', handlers.MaterializeFaqRequestHandler, name='materialize-faq', strict_slash=True),
    RedirectRoute('/user/tou/', handlers.MaterializeTouRequestHandler, name='materialize-tou', strict_slash=True),
    RedirectRoute('/user/privacy/', handlers.MaterializePrivacyRequestHandler, name='materialize-privacy', strict_slash=True),
    RedirectRoute('/user/contact/', handlers.MaterializeContactRequestHandler, name='materialize-contact', strict_slash=True),
    RedirectRoute('/user/change-email/<user_id>/<encoded_email>/<token>', handlers.MaterializeEmailChangedCompleteHandler, name='materialize-email-changed-check', strict_slash=True),
    
    # Statics
    RedirectRoute(r'/robots.txt', handlers.RobotsHandler, name='robots', strict_slash=True),
    RedirectRoute(r'/humans.txt', handlers.HumansHandler, name='humans', strict_slash=True),
    RedirectRoute(r'/sitemap.xml', handlers.SitemapHandler, name='sitemap', strict_slash=True),
    RedirectRoute(r'/crossdomain.xml', handlers.CrossDomainHandler, name='crossdomain', strict_slash=True),
    
    #Cronjobs
    RedirectRoute('/cronjob-welcome/', handlers.WelcomeCronjobHandler, name='cronjob-welcome', strict_slash=True),  
    
    #Taskqueues
    RedirectRoute('/taskqueue-send-email/', handlers.SendEmailHandler, name='taskqueue-send-email', strict_slash=True),
    RedirectRoute('/taskqueue-welcome/', handlers.WelcomeHandler, name='taskqueue-welcome', strict_slash=True),

    #API
    RedirectRoute('/mbapi/in/', handlers.APIIncomingHandler, name='mbapi-in', strict_slash=True),
    RedirectRoute('/mbapi/out/', handlers.APIOutgoingHandler, name='mbapi-out', strict_slash=True),
    RedirectRoute('/mbapi/test/', handlers.APITestingHandler, name='mbapi-test', strict_slash=True),

    # Blob handlers
    RedirectRoute('/img/upload/', handlers.AvatarUploadHandler, name='img-upload', strict_slash=True),
    RedirectRoute('/img/', handlers.AvatarDownloadHandler, name='img-download', strict_slash=True),
    RedirectRoute('/cover/upload/', handlers.CoverUploadHandler, name='cover-upload', strict_slash=True),
    RedirectRoute('/cover/', handlers.CoverDownloadHandler, name='cover-download', strict_slash=True),
    
]

def get_routes():
    return _routes

def add_routes(app):
    if app.debug:
        secure_scheme = 'http'
    for r in _routes:
        app.router.add(r)