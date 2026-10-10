// After deployment, copy ApiUrl, AuthDomain, and UserPoolClientId from CloudFormation outputs.
window.MERCHANT_APP_CONFIG = {
  apiBaseUrl: "",
  demoMode: true,
  authDomain: "",
  userPoolClientId: "",
  redirectUri: window.location.origin + "/"
};
