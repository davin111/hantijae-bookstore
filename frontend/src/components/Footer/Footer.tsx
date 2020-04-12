import React, { Component } from 'react';
import Grid from '@material-ui/core/Grid';
import Box from '@material-ui/core/Box';
import Typography from '@material-ui/core/Typography';
import TextField from '@material-ui/core/TextField';

import './Footer.css';

interface Props {
  history: any;
}

// eslint-disable-next-line react/prefer-stateless-function
class Footer extends Component<Props> {
  render() {
    return (
      <div>
        <footer>
          <div className="FooterInfo">
            {/* <div className="LeftFooter">
              도서출판 한티재
            </div>
            <div className="RightFooter">
              그렇다
            </div> */}
            <>
              <Typography variant="h6" gutterBottom>
                주문 정보 입력
              </Typography>
              <Grid container spacing={3}>
                <Grid item xs={12} sm={12}>
                  <TextField
                    required
                    id="firstName"
                    name="firstName"
                    label="이름 (주문하는 분)"
                    fullWidth
                    autoComplete="fname"
                    onChange={(e) => this.props.changeGivenName(e)}
                    value={this.props.givenName}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <TextField
                    required
                    fullWidth
                    id="email"
                    label="이메일"
                    name="email"
                    autoComplete="email"
                    onChange={(e) => this.props.changeEmail(e)}
                    value={this.props.email}
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <TextField
                    required
                    id="phonenumber"
                    name="phonenumber"
                    label="휴대전화 번호"
                    fullWidth
                    autoComplete="tel"
                    helperText="'-'를 제외하고 입력해주세요."
                    onChange={(e) => this.props.changePhoneNumber(e)}
                    value={this.props.phoneNumber}
                  />
                </Grid>
              </Grid>
            </>
          </div>
        </footer>
      </div>
    );
  }
}

export default Footer;
