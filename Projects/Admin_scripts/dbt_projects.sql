-------------------------------------------DCM--DEV------------------------------------------------------------
use role GITHUB_CICD_DEMO_ROLE;
USE DATABASE CICD_AUTOMATION_DEV;
CREATE DCM PROJECT IF NOT EXISTS CICD_AUTOMATION_DEV.UTILITIES.DCM_AUTOMATION
COMMENT = 'DCM Project - Dev';

--------------------DBT--DEV-------------------------------------------------------------------------
use role GITHUB_CICD_DEMO_ROLE;
use database CICD_AUTOMATION_DEV;
create or replace dbt project CICD_AUTOMATION_DEV.UTILITIES.DCM_DBT_CICD
from snow://workspace/USER$DISHA_RANI.PUBLIC.CI_CD_STANDARD_TIER_OFFERING_TEMPLATE/versions/live/dcm_dbt_cicd/
DBT_VERSION='1.9.4'
DEFAULT_TARGET='DCM_DEV'
EXTERNAL_ACCESS_INTEGRATIONS=();

-----------------------------------------------DCM--PROD-----------------------------------------------------------------------------------------


use role GITHUB_CICD_DEMO_ROLE;
USE DATABASE CICD_AUTOMATION_PROD;
CREATE OR REPLACE  SCHEMA CICD_AUTOMATION_PROD.UTILITIES;
CREATE DCM PROJECT IF NOT EXISTS CICD_AUTOMATION_PROD.UTILITIES.DCM_AUTOMATION
COMMENT = 'DCM Project - Prod';

---------------------------------------------------------DBT--PROD-----------------------------------------------------------------

create or replace dbt project CICD_AUTOMATION_PROD.UTILITIES.DCM_DBT_CICD
from snow://workspace/USER$DISHA_RANI.PUBLIC.CI_CD_STANDARD_TIER_OFFERING_TEMPLATE/versions/live/dcm_dbt_cicd/
DBT_VERSION='1.9.4'
DEFAULT_TARGET='DCM_PROD'
EXTERNAL_ACCESS_INTEGRATIONS=();

-----------------------------------------DCM--QA-----------------------------------------------
use role GITHUB_CICD_DEMO_ROLE;
USE DATABASE CICD_AUTOMATION_QA;
CREATE DCM PROJECT IF NOT EXISTS CICD_AUTOMATION_QA.UTILITIES.DCM_AUTOMATION
COMMENT = 'DCM Project - QA';

---------------------------------------------------------DBT--QA-----------------------------------------------------------------

create or replace dbt project CICD_AUTOMATION_QA.UTILITIES.DCM_DBT_CICD
from snow://workspace/USER$DISHA_RANI.PUBLIC.CI_CD_STANDARD_TIER_OFFERING_TEMPLATE/versions/live/dcm_dbt_cicd/
DBT_VERSION='1.9.4'
DEFAULT_TARGET='DCM_QA'
EXTERNAL_ACCESS_INTEGRATIONS=();