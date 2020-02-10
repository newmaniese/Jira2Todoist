#! /usr/bin/env fish
rm -rf build
mkdir build; and \
pip install -r (pipenv lock -r |psub) --target build/; and \
# pip install . -U --target build/; and \
cp lambda.py build/; and \
cd build; and \
zip -r build.zip *; and \
aws lambda update-function-code --function-name Jira2Todoist --zip-file fileb://$PWD/build.zip --region "us-west-2"; and \
cd ..; and rm -rf build