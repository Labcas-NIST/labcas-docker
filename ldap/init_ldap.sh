#!/bin/bash
set -e

# Add initial LDAP data
ldapadd -x -H ldap://localhost:1389 -D "cn=admin,dc=labcas,dc=jpl,dc=nasa,dc=gov" -w secret -f /tmp/ldap/create_groups_ou.ldif
ldapadd -x -H ldap://localhost:1389 -D "cn=admin,dc=labcas,dc=jpl,dc=nasa,dc=gov" -w secret -f /tmp/ldap/add_user_dliu.ldif
ldapadd -x -H ldap://localhost:1389 -D "cn=admin,dc=labcas,dc=jpl,dc=nasa,dc=gov" -w secret -f /tmp/ldap/create_superuser_group.ldif
